import fs from 'node:fs';
import path from 'node:path';
const out=path.resolve('build');fs.mkdirSync(out,{recursive:true});
const css=fs.readFileSync('dist/style.css','utf8').replace(/^@import[^\n]*\n/,'');
const campaignCSS=fs.readFileSync('dist/campaign.css','utf8');
const engine=fs.readFileSync('dist/engine.js','utf8').replace(/^export /gm,'');
const terminal=fs.readFileSync('dist/terminal.js','utf8').replace(/^import[^\n]+\n/gm,'').replace(/^export /gm,'');
const terminalUI=fs.readFileSync('dist/terminal-ui.js','utf8').replace(/^import[^\n]+\n/gm,'').replace(/^export /gm,'');
const campaignUI=fs.readFileSync('dist/campaign-ui.js','utf8').replace(/^import[^\n]+\n/gm,'').replace(/^export /gm,'');
const game=fs.readFileSync('dist/game.js','utf8').replace(/^import[^\n]+\n/gm,'');
let html=fs.readFileSync('dist/index.html','utf8').replace('<link rel="stylesheet" href="style.css">',()=>'<style>'+css+'</style>').replace('<link rel="stylesheet" href="campaign.css">',()=>'<style>'+campaignCSS+'</style>').replace('<script type="module" src="game.js"></script>',()=>'<script>\n'+engine+'\n'+terminal+'\n'+terminalUI+'\n'+campaignUI+'\n'+game+'\n</script>');
for(const asset of ['occupied-earth-map.png','overseer-sentinel.png']){html=html.replaceAll('assets/'+asset,'data:image/png;base64,'+fs.readFileSync('dist/assets/'+asset).toString('base64'));}
html=html.replace('href="v1.html"','href="https://bitforge-binary-lab.donjuanconsonftw.chatgpt.site/v1.html"');
fs.writeFileSync(path.join(out,'Bitforge.html'),html);console.log('Self-contained offline game: '+path.join(out,'Bitforge.html'));
