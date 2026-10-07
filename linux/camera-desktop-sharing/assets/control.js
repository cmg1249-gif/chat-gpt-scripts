'use strict';
const $ = id => document.getElementById(id);
let csrf = '', connected = false, state = {}, viewing = false, term = null, cursor = 0, generation = 0, terminalRunning = false, terminalPollBusy = false;
let audioContext = null, audioAbort = null, listening = false, nextAudioTime = 0;
const audioNodes = new Set();
function fail(error) { $('error').textContent = error.message || String(error); $('error').hidden = false; }
function clearError() { $('error').hidden = true; $('error').textContent = ''; }
async function api(path, method = 'GET', data) {
  const options = {method, headers: {'X-RoomCam-CSRF': csrf}};
  if (data !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(data); }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw Error((result.error || `Request failed (${response.status})`) + (result.hint ? '\n' + result.hint : ''));
  return result;
}
function remote(path, method = 'GET', data) { return api('/remote' + path, method, data); }
function action(id, fn) { $(id).onclick = async () => { clearError(); try { await fn(); } catch (e) { fail(e); } }; }
function showTab(tab) {
  document.querySelectorAll('[data-tab]').forEach(el => el.classList.toggle('active', el.dataset.tab === tab));
  ['overview', 'terminal', 'activity'].forEach(name => $(name + '-panel').hidden = name !== tab);
  $('title').textContent = {overview: 'Control center', terminal: 'Host terminal', activity: 'Connection & activity'}[tab];
  if (tab === 'terminal' && term) setTimeout(resizeTerminal, 0);
  if (tab === 'activity' && connected) refreshLogs().catch(fail);
}
document.querySelectorAll('[data-tab]').forEach(el => el.onclick = () => showTab(el.dataset.tab));
function setConnected(value, info = {}) {
  connected = value; $('connect-card').hidden = value; $('workspace').hidden = !value; $('disconnect').hidden = !value;
  $('route').textContent = value ? info.route : 'Offline'; $('route').classList.toggle('on', value); $('side-dot').classList.toggle('on', value);
  $('side-status').textContent = value ? 'Host connected' : 'No host connected';
  if (value) { $('host-name').textContent = info.host || 'Sharing computer'; $('host-os').textContent = info.platform || ''; $('connection-name').textContent = info.route; $('footer-status').textContent = 'Connected · ' + info.version; }
  else { $('footer-status').textContent = 'Ready when you are.'; showTab('overview'); }
}
function options(id, entries, selected) { $(id).replaceChildren(...entries.map(item => { const el = document.createElement('option'); el.value = item.id; el.textContent = item.name; el.selected = String(item.id) === String(selected); return el; })); }
async function refreshDevices(probe = false) {
  const d = await remote('/devices' + (probe ? '?probe=1' : ''));
  options('camera', d.cameras.map(c => ({id: c.index, name: c.name})), d.current_camera);
  options('monitor', d.monitors.map(m => ({id: m.id, name: `${m.name} · ${m.width} × ${m.height}`})), d.monitor);
  options('microphone', [{id: -1, name: 'System default'}, ...d.microphones.map(m => ({id: m.index, name: m.name}))], d.current_mic);
}
async function refreshState() {
  if (!connected) return;
  state = await remote('/status');
  $('capture-state').textContent = state.active ? 'Video active' : (state.mic || state.desktop_audio ? 'Audio active' : 'Capture off');
  for (const [id, value] of [['mic', state.mic], ['desktop', state.desktop_audio]]) { $(id).querySelector('span').textContent = value ? 'On' : 'Off'; $(id).classList.toggle('on', value); }
  const health = await remote('/control/status');
  const connection = await api('/connection');
  if (connection.connected && connection.route !== $('route').textContent) {
    $('route').textContent = connection.route; $('connection-name').textContent = connection.route;
    $('notice').textContent = 'Connection recovered using ' + connection.route + '. Restart viewing or listening if its stream stopped.';
  }
  $('shell-state').textContent = health.terminal ? 'Shell active' : 'Shell closed';
  $('lan-health').textContent = health.lan; $('internet-health').textContent = health.internet; $('version').textContent = health.version;
  if (state.audio_error) fail(state.audio_error);
}
async function refreshLogs() { const log = await remote('/logs'); $('logs').textContent = log.lines.join('\n') || 'No activity yet.'; }
$('connect-form').onsubmit = async event => {
  event.preventDefault(); clearError(); $('connect').disabled = true; $('connect').textContent = 'Connecting…'; $('connect-progress').textContent = 'Finding your host and authorizing your viewer…';
  try {
    const info = await api('/connect', 'POST', {username: $('username').value, password: $('password').value, mode: $('mode').value, address: $('address').value});
    setConnected(true, info);
    await refreshState();
    // Device scanning is explicit: it may briefly open cameras on some systems.
    const displays = await remote('/monitors'); options('monitor', displays.monitors.map(m => ({id: m.id, name: m.name + ' · ' + m.width + ' × ' + m.height})), displays.selected);
  } catch (e) { fail(e); }
  finally { $('connect').disabled = false; $('connect').innerHTML = 'Connect to computer <span>→</span>'; $('connect-progress').textContent = 'Run webcam_server, then connect. Local network first, internet fallback.'; }
};
function stopVideo() { viewing = false; $('feed').removeAttribute('src'); $('feed').hidden = true; $('empty-view').hidden = false; $('view-badge').textContent = 'Stopped'; $('view-badge').classList.remove('on'); $('view-detail').textContent = 'No video stream running'; $('start-view').textContent = 'Start viewing'; }
async function startView() {
  const source = $('source').value;
  if (source === 'camera') await remote('/camera/select?index=' + ($('camera').value || '0'), 'POST');
  await remote('/source/select?source=' + source + '&monitor=' + ($('monitor').value || '1'), 'POST');
  $('feed').src = '/remote/video?t=' + Date.now(); $('feed').hidden = false; $('empty-view').hidden = true; viewing = true;
  $('view-badge').textContent = 'Live'; $('view-badge').classList.add('on'); $('view-detail').textContent = source === 'desktop' ? 'Desktop · monitor ' + $('monitor').value : 'Camera'; $('start-view').textContent = 'Apply source';
  await refreshState();
}
$('feed').onerror = () => { if (viewing) { stopVideo(); fail('Video stopped. Refresh devices, choose a source, and try again.'); } };
action('start-view', startView); action('refresh', () => refreshDevices(true));
action('mic', async () => { await refreshState(); await remote(state.mic ? '/mic/stop' : '/mic/start', 'POST'); await refreshState(); });
action('desktop', async () => { await refreshState(); await remote(state.desktop_audio ? '/desktop-audio/stop' : '/desktop-audio/start', 'POST'); await refreshState(); });
$('microphone').onchange = () => remote('/mic/select?index=' + $('microphone').value, 'POST').then(refreshState).catch(fail);
action('stop', async () => { stopVideo(); stopListening(); await Promise.all(['/stop', '/mic/stop', '/desktop-audio/stop'].map(path => remote(path, 'POST'))); await refreshState(); });
action('disconnect', async () => { stopVideo(); stopListening(); terminalUI(false); setConnected(false); await api('/disconnect', 'POST'); });
action('logs-refresh', refreshLogs);
function stopListening() { listening = false; if (audioAbort) audioAbort.abort(); for (const node of audioNodes) { try { node.stop(); } catch {} } audioNodes.clear(); nextAudioTime = 0; $('listen').textContent = 'Listen on this computer'; }
function playAudio(bytes) {
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), count = bytes.length / 4;
  if (nextAudioTime > audioContext.currentTime + 2) return;
  const buffer = audioContext.createBuffer(2, count, 48000);
  for (let channel = 0; channel < 2; channel++) { const target = buffer.getChannelData(channel); for (let i = 0; i < count; i++) target[i] = data.getInt16((i * 2 + channel) * 2, true) / 32768; }
  const node = audioContext.createBufferSource(); node.buffer = buffer; node.connect(audioContext.destination); audioNodes.add(node); node.onended = () => { audioNodes.delete(node); node.disconnect(); };
  nextAudioTime = Math.max(nextAudioTime, audioContext.currentTime + .15); node.start(nextAudioTime); nextAudioTime += buffer.duration;
}
action('listen', async () => {
  if (listening) { stopListening(); return; }
  audioContext = audioContext || new AudioContext(); await audioContext.resume(); audioAbort = new AbortController(); listening = true; $('listen').textContent = 'Mute local playback';
  try {
    const response = await fetch('/remote/audio', {signal: audioAbort.signal}); if (!response.ok) throw Error('Audio stream failed.');
    const reader = response.body.getReader(); let pending = new Uint8Array();
    while (listening) { const {done, value} = await reader.read(); if (done) break; const merged = new Uint8Array(pending.length + value.length); merged.set(pending); merged.set(value, pending.length); pending = merged;
      while (pending.length >= 14) { const size = new DataView(pending.buffer, pending.byteOffset, 14).getUint16(12); if (size % 4) throw Error('Invalid audio packet.'); if (pending.length < 14 + size) break; if (size) playAudio(pending.slice(14, 14 + size)); pending = pending.slice(14 + size); }
    }
  } catch (e) { if (e.name !== 'AbortError') throw e; } finally { stopListening(); }
});
function terminalUI(running) { terminalRunning = running; $('terminal-open').disabled = running; $('terminal-close').disabled = !running; $('terminal-interrupt').disabled = !running; $('terminal-empty').hidden = running || Boolean(term); $('terminal').hidden = !term; $('terminal-status').textContent = running ? 'Shell active · input goes to the host' : 'Shell closed'; }
let inputQueue = '', inputBusy = false;
async function sendInput(data) {
  inputQueue += data;
  if (inputBusy) return;
  inputBusy = true;
  try { while (inputQueue && terminalRunning) { const chunk = inputQueue.slice(0, 4000); inputQueue = inputQueue.slice(chunk.length); await remote('/terminal/input', 'POST', {data: chunk}); } }
  catch (e) { inputQueue = ''; fail(e); }
  finally { inputBusy = false; }
}
async function resizeTerminal() { if (!term || !terminalRunning) return; const cols = Math.max(20, Math.min(240, Math.floor(($('terminal').clientWidth - 45) / 8.5))); term.resize(cols, 26); try { await remote('/terminal/resize', 'POST', {rows: 26, cols}); } catch (e) { fail(e); } }
action('terminal-open', async () => {
  await remote('/terminal', 'POST');
  if (!term) { term = new Terminal({cursorBlink: true, fontSize: 14, fontFamily: 'Consolas, Menlo, monospace', rows: 26, cols: 100, theme: {background: '#0c121c', foreground: '#d3e3f2', cursor: '#75e6c0'}, allowProposedApi: false}); $('terminal').hidden = false; term.open($('terminal')); term.onData(data => { if (terminalRunning) sendInput(data); }); }
  term.reset(); cursor = 0; generation = 0; terminalUI(true); await resizeTerminal(); term.focus(); await pollTerminal(); await refreshState();
});
action('terminal-close', async () => { terminalUI(false); await remote('/terminal', 'DELETE'); await refreshState(); });
action('terminal-interrupt', () => sendInput('\u0003'));
async function pollTerminal() {
  if (!connected || !term || !terminalRunning || terminalPollBusy) return;
  terminalPollBusy = true;
  try { const data = await remote(`/terminal?cursor=${cursor}&generation=${generation}`); if (!connected || !terminalRunning) return; if (data.reset) term.reset(); if (data.output) term.write(data.output); cursor = data.cursor; generation = data.generation; terminalUI(data.running); if (data.reason) $('terminal-status').textContent = data.reason; }
  catch (e) { if (connected && terminalRunning) { terminalUI(false); fail(e); } }
  finally { terminalPollBusy = false; }
}
window.addEventListener('resize', resizeTerminal); window.addEventListener('pagehide', stopListening);
setInterval(pollTerminal, 200); setInterval(() => { if (connected) refreshState().catch(fail); }, 5000);
(async () => { try { const token = new URLSearchParams(location.hash.slice(1)).get('launch') || ''; history.replaceState(null, '', '/'); const result = await api('/bootstrap', 'POST', {token}); csrf = result.csrf; const settings = await api('/owner-settings'); if (settings.saved) { $('password').placeholder = 'Leave blank to use your saved private password'; $('saved-password').textContent = 'Your private password is saved on this viewer.'; } const connection = await api('/connection'); if (connection.connected) { const health = await remote('/control/status'); setConnected(true, {...connection, ...health}); await refreshState(); } } catch (e) { $('connect').disabled = true; fail(e); } })();
