export const LAYERS=[
{name:'Physical',job:'Carries bits as electrical, optical, or radio signals.'},
{name:'Data Link',job:'Delivers frames on a local link, using MAC addresses.'},
{name:'Network',job:'Addresses and routes packets between networks using IP.'},
{name:'Transport',job:'Provides process-to-process delivery using ports; TCP and UDP live here.'},
{name:'Session',job:'Organizes, maintains, and ends dialogues between applications in the OSI model.'},
{name:'Presentation',job:'Represents data in a format the receiving application can understand.'},
{name:'Application',job:'Provides network services such as HTTP and DNS to applications.'}];
export const OSI_CASES=[
['A fiber cable is broken. No light reaches the receiver.',1,'The signal cannot travel through the physical medium.'],
['An Ethernet switch uses a destination MAC address to forward a frame.',2,'MAC addresses and Ethernet frames concern the local data link.'],
['A router chooses the next hop for an IP packet.',3,'Routing between IP networks is a network-layer function.'],
['TCP uses port numbers to deliver data to the right process.',4,'Transport separates conversations between processes.'],
['A system establishes and manages a dialogue between two applications.',5,'Dialogue management is the session layer’s role in the OSI model.'],
['The sender and receiver agree on how characters are represented as bytes.',6,'Data representation is the presentation layer’s conceptual role.'],
['A DNS service answers a request for the address of portal.test.',7,'DNS is an application-layer protocol.'],
['An HTTP server answers a browser with 503 Service Unavailable.',7,'The HTTP service is responding at the application layer.'],
['A wireless signal is too weak for the receiver to detect the transmitted bits.',1,'Radio signaling belongs to the physical layer.'],
['An Ethernet frame contains source and destination MAC addresses.',2,'Frames and MAC addressing operate at the data link layer.'],
['Two hosts sit in different IP subnets and need a router to communicate.',3,'IP addressing and inter-network routing belong to the network layer.'],
['UDP delivers a datagram to a destination port without TCP-style retransmission.',4,'UDP is a transport protocol; transport does not always guarantee delivery.'],
['In the OSI reference model, a dialogue is resumed from a synchronization point.',5,'Dialogue synchronization is a session-layer responsibility.'],
['In the OSI reference model, data is translated between representation formats.',6,'Formatting and translation are presentation-layer functions.']];
export const SECTORS=[
{name:'Deadlight relay',topic:'4-bit binary',tag:'CALIBRATE THE LINK',cost:0,color:'#b6f36b',lesson:'A bit is a 0 or a 1. From right to left, the places are worth 1, 2, 4, 8. Add the places switched on.',story:'Reconnect an abandoned resistance relay. Its four-bit controller is your way in.'},
{name:'Cache district',topic:'8-bit numbers',tag:'EXPAND YOUR RANGE',cost:4,color:'#74dce5',lesson:'Eight bits make a byte: 128, 64, 32, 16, 8, 4, 2, 1. Values run from 0 to 255. Labels disappear after four repairs; you can reveal them when needed.',story:'Recover a captured maintenance depot and the components locked inside.'},
{name:'Address docks',topic:'IPv4 octets',tag:'ADDRESS THE WORLD',cost:5,color:'#ffb975',lesson:'An IPv4 address contains four 8-bit octets, each 0–255. Convert each octet independently.',story:'Readdress liberated servers so resistance cells can communicate.'},
{name:'Mask checkpoint',topic:'CIDR · subnet masks',tag:'DRAW THE BOUNDARIES',cost:6,color:'#82b7ff',lesson:'A /n prefix has n network bits and 32 − n host bits. A subnet mask has leading 1s, then 0s. /26 is 255.255.255.192.',story:'Rebuild the subnet boundaries around a reclaimed command post.'},
{name:'Subnet frontier',topic:'Networks · hosts · routing',tag:'CONNECT THE SITES',cost:7,color:'#f394c2',lesson:'For /24–/30, block size = 2^(32 − prefix). The first address is the network, the last is broadcast, and the addresses between are usable hosts.',story:'Connect scattered resistance sites across the occupied network.'},
{name:'Overseer core',topic:'OSI model · troubleshooting',tag:'FOLLOW THE EVIDENCE',cost:8,color:'#c2a2ff',lesson:'OSI is a seven-layer reference model: Physical, Data Link, Network, Transport, Session, Presentation, Application. Identify the function or fault, then the layer. Real TCP/IP systems do not always separate all seven layers.',story:'Bring the final human command server online. Diagnose faults across the OSI model to finish the recovery.'}
];
export const UPGRADES=[
{id:'yield',name:'Recovery toolkit',branch:0,icon:'◇',cost:3,credits:40,desc:'Recover 50% more components from each maintenance cache after a verified recovery task.',needs:[]},
{id:'combo',name:'Clean recovery',branch:0,icon:'≋',cost:4,credits:60,desc:'Three consecutive unassisted, first-try tasks preserve 15 extra components during recovery.',needs:['yield']},
{id:'overdrive',name:'Priority salvage',branch:0,icon:'✧',cost:7,credits:100,desc:'Locate five larger caches with twice the components. Recon finds another batch after ten regular tasks.',needs:['combo'],sector:2},
{id:'rush',name:'Recovery sprint',branch:1,icon:'◷',cost:3,credits:50,desc:'Optional 60-second practice runs. Keep your rewards; beat your own record.',needs:[],sector:1},
{id:'aurora',name:'Aurora resistance console',branch:1,icon:'❖',cost:2,credits:100,desc:'Personalize your workstation with a violet network display.',needs:[]}
];
export const binary=(n,w=8)=>n.toString(2).padStart(w,'0');
export const clamp=(n,a,b)=>Math.min(b,Math.max(a,n));
export const freshState=()=>({version:3,energy:0,shards:0,xp:0,sector:0,unlocked:[0],counts:[0,0,0,0,0,0],attempts:[0,0,0,0,0,0],firstTry:[0,0,0,0,0,0],upgrades:[],streak:0,bestStreak:0,total:0,assisted:0,bestRush:0,finalStep:0,won:false,overdrive:0,overCooldown:0,terminalCompleted:[],installedModules:[],settings:{sound:false,motion:true},badges:[]});
export function validateSave(raw){
if(!raw||![1,2,3].includes(raw.version))throw Error('This is not a supported Bitforge save.');
const old=raw.version===1,s=freshState(),map=[0,1,3,4,5,-1];
for(const k of ['energy','shards','xp','sector','streak','bestStreak','total','assisted','bestRush','finalStep','overdrive','overCooldown']){if(!Number.isFinite(raw[k])||raw[k]<0)throw Error('Invalid '+k+' in save.');s[k]=Math.floor(Math.min(raw[k],1e9));}
for(const k of ['counts','attempts','firstTry']){if(!Array.isArray(raw[k])||raw[k].length!==6||raw[k].some(n=>!Number.isFinite(n)||n<0))throw Error('Invalid learning progress.');s[k]=(old?map.map(i=>i<0?0:raw[k][i]):raw[k]).map(n=>Math.min(1e7,Math.floor(n)));}
if(!Array.isArray(raw.unlocked)||raw.unlocked.some(n=>!Number.isInteger(n)||n<0||n>5))throw Error('Invalid sectors.');
s.unlocked=[...new Set([0,...(old?raw.unlocked.map(i=>map.indexOf(i)).filter(i=>i>=0):raw.unlocked)])];
s.sector=old?Math.max(0,map.indexOf(raw.sector)):clamp(s.sector,0,5);if(!s.unlocked.includes(s.sector))s.sector=0;
s.upgrades=Array.isArray(raw.upgrades)?[...new Set(raw.upgrades.filter(id=>UPGRADES.some(u=>u.id===id)))]:[];
if(old){const refund={drone:5,loop:5,speed:6,scanner:2};s.shards+=(raw.upgrades||[]).reduce((n,id)=>n+(refund[id]||0),0);s.energy+=(raw.relayLevels||[]).reduce((n,level)=>n+30*clamp(Number(level)||0,0,3)*(clamp(Number(level)||0,0,3)+1),0);s.finalStep=0;s.total=s.counts.reduce((a,b)=>a+b,0);s.assisted=Math.min(s.assisted,s.total);s.migrated=true;}
s.finalStep=clamp(s.finalStep,0,6);s.overdrive=clamp(s.overdrive,0,5);s.overCooldown=clamp(s.overCooldown,0,10);s.won=!old&&raw.won===true&&s.finalStep===6&&s.counts.every(n=>n>=8);
s.terminalCompleted=!old&&Array.isArray(raw.terminalCompleted)?[...new Set(raw.terminalCompleted.filter(n=>Number.isInteger(n)&&n>=0&&n<6))]:[];
s.installedModules=raw.version===3&&Array.isArray(raw.installedModules)?[...new Set(raw.installedModules.filter(n=>Number.isInteger(n)&&n>=1&&n<=6))]:[];
if(s.installedModules.length>s.terminalCompleted.length)throw Error('Invalid module inventory.');
if(raw.version<3){const refunds={routeLab:[2,40],dnsLab:[3,60],serviceLab:[3,80]};for(const id of new Set(raw.upgrades||[])){if(refunds[id]){s.shards+=refunds[id][0];s.energy+=refunds[id][1];}}s.economyMigrated=true;}
s.badges=Array.isArray(raw.badges)?raw.badges.filter(x=>typeof x==='string'&&!['auto',...(old?['network']:[])].includes(x)):[];
s.settings={sound:raw.settings?.sound===true,motion:raw.settings?.motion!==false};return s;}
export function learningSupport(s,q,revealed=false){return revealed||q.sector<2&&s.counts[q.sector]<4;}
export function subnet(last,prefix){const size=2**(32-prefix),network=Math.floor(last/size)*size;return{size,network,broadcast:network+size-1,hosts:size-2,mask:256-size};}
export function challenge(sector,progress=0,rng=Math.random){
 const r=(a,b)=>Math.floor(rng()*(b-a+1))+a, pick=a=>a[r(0,a.length-1)];
 const q={sector,kind:'bits',width:4,title:'Forge a signal.',prompt:'Turn on the places that add up to the target.',label:'TARGET DECIMAL',reward:4+sector*2};
 const enc=(n,w=4)=>{q.expected=n;q.width=w;q.display=String(n);q.hint=`Choose the largest place that fits, subtract it, then repeat. ${n===0?'Zero means every switch is off.':`Start with ${2**Math.floor(Math.log2(n))}.`}`;q.explain=`${binary(n,w)} = ${[...binary(n,w)].map((v,i)=>v==='1'?2**(w-1-i):0).filter(Boolean).join(' + ')||'0'} = ${n}.`;};
 const dec=(n,w=8)=>{enc(n,w);q.kind='number';q.title='Read the incoming signal.';q.prompt='Add the place values where the bit is 1.';q.label='INCOMING BINARY';q.display=binary(n,w);q.hint='Write the place values above the bits. Add only the places marked 1.';};
 if(sector===0){const sequence=[5,3,9,6,12,10,0,15];enc(progress<8?sequence[progress]:r(0,15));if(progress>=8&&progress%3===1)dec(r(0,15),4);}
 if(sector===1){const n=progress===0?42:progress===1?128:r(0,255);progress%2?dec(n):enc(n,8);}
 if(sector===2){const n=pick([10,16,42,64,100,128,168,192,200,224,254,r(0,255)]);if(progress%2===0){dec(n);q.title='Decode the address.';q.label='LAST OCTET IN BINARY';q.prompt='The packet is going to 192.168.1.?. Decode its last octet.';q.explain=`${binary(n)} = ${n}. The full address is 192.168.1.${n}.`;}else{enc(n,8);q.title='Encode an IP octet.';q.label='ENCODE THE LAST OCTET';q.display=`10.0.0.${n}`;q.prompt=`Send the last octet (${n}) as eight binary bits.`;}}
 if(sector===3){const prefix=progress===0?26:r(24,30),s=subnet(0,prefix);q.width=8;q.title='Build the subnet mask.';q.prompt='The first three mask octets are 255. Set the eight bits of the final octet.';q.label='NETWORK PREFIX';q.display='/'+prefix;q.expected=s.mask;q.hint=`/${prefix} uses ${prefix-24} leading 1s in the last octet, then ${32-prefix} zeros.`;q.explain=`/${prefix} = 255.255.255.${s.mask}. Last octet: ${binary(s.mask)}; ${32-prefix} host bits remain.`;if(progress%3===2){q.kind='number';q.title='Count the host bits.';q.prompt='IPv4 has 32 bits. How many bits are left for hosts?';q.expected=32-prefix;q.explain=`32 − ${prefix} = ${32-prefix} host bits. That gives ${s.size} total addresses.`;q.hint='Subtract the prefix length from 32.';}}
 if(sector===4){const prefix=r(25,30),last=r(1,254),s=subnet(last,prefix),base='192.168.1.';q.kind='text';q.title='Route the packet.';q.display=base+last+'/'+prefix;q.label='PACKET ADDRESS';const mode=progress%4;if(mode===0){q.prompt='Enter the network address this packet belongs to.';q.expected=base+s.network;q.hint=`Block size = 2^${32-prefix} = ${s.size}. Find the multiple of ${s.size} at or below ${last}.`;q.explain=`${last} is in the ${s.network}–${s.broadcast} block. Network: ${q.expected}.`;}if(mode===1){q.title='Find the broadcast.';q.prompt='Enter the broadcast address (the last address in this block).';q.expected=base+s.broadcast;q.hint=`The block starts at ${s.network} and has ${s.size} addresses. End = start + size − 1.`;q.explain=`${s.network} + ${s.size} − 1 = ${s.broadcast}. Broadcast: ${q.expected}.`;}if(mode===2){q.kind='number';q.title='Make room for the hosts.';q.prompt='How many usable host addresses are in this subnet?';q.expected=s.hosts;q.hint=`There are ${s.size} total addresses. Reserve one for the network and one for broadcast.`;q.explain=`2^${32-prefix} − 2 = ${s.hosts} usable hosts (${base}${s.network+1} to ${base}${s.broadcast-1}).`;}if(mode===3){const need=pick([2,5,10,25,50,100]);const p=[30,29,28,27,26,25].find(p=>2**(32-p)-2>=need);q.kind='choice';q.title='Choose the right neighborhood.';q.display=String(need);q.label='DEVICES NEEDING ADDRESSES';q.prompt='Choose the smallest subnet that fits all devices (fewest total addresses).';q.options=['/25','/26','/27','/28','/29','/30'];q.expected='/'+p;q.hint='Compare usable hosts: /30 → 2, /29 → 6, /28 → 14, /27 → 30, /26 → 62, /25 → 126.';q.explain=`/${p} supports ${2**(32-p)-2} usable hosts, the smallest listed block that fits ${need}.`;}}
 if(sector===5){const item=OSI_CASES[progress<OSI_CASES.length?progress:r(0,OSI_CASES.length-1)];q.kind='choice';q.title='Trace the fault to its layer.';q.label='INCIDENT REPORT';q.display=item[0];q.prompt='Which OSI layer is responsible for the function described?';q.options=LAYERS.map((x,i)=>(i+1)+' · '+x.name);q.expected=q.options[item[1]-1];q.hint=LAYERS[item[1]-1].job;q.explain='Layer '+item[1]+' — '+LAYERS[item[1]-1].name+'. '+item[2];}
 return q;
}
export function checkAnswer(q,value){if(q.kind==='bits'||q.kind==='number')return String(value).trim()!==''&&/^\d+$/.test(String(value).trim())&&Number(value)===q.expected;return String(value).trim()===String(q.expected);}
export function award(s,q,{first=true,assisted=false}={}){const boost=s.overdrive>0?2:1;let energy=Math.floor(q.reward*(s.upgrades.includes('yield')?1.5:1))*boost;s.streak=first&&!assisted?s.streak+1:0;s.bestStreak=Math.max(s.bestStreak,s.streak);if(s.upgrades.includes('combo')&&s.streak>0&&s.streak%3===0)energy+=15;s.energy+=energy;s.shards++;s.xp+=20+q.sector*5;s.total++;s.counts[q.sector]++;if(first&&!assisted)s.firstTry[q.sector]++;if(assisted)s.assisted++;if(s.overdrive>0)s.overdrive--;else if(s.overCooldown>0)s.overCooldown--;return energy;}
export function canUnlock(s,i){return i>0&&i<6&&!s.unlocked.includes(i)&&s.unlocked.includes(i-1)&&s.counts[i-1]>=6&&s.shards>=SECTORS[i].cost&&s.energy>=SITE_COMPONENTS[i]&&s.terminalCompleted.includes(i-1)&&availableModules(s)>0;}
export function restored(s,index){return index>=0&&index<24&&s.counts[Math.floor(index/4)]>=(index%4+1)*2;}

// Workstation hardware is finite; practice currency stays renewable.
export const SITE_COMPONENTS=[0,80,110,140,180,230];
export const WORKSTATION_REWARDS=[90,120,160,210,270,340];
export const availableModules=s=>s.terminalCompleted.length-s.installedModules.length;
export function terminalAvailable(s,id){return Number.isInteger(id)&&id>=0&&id<6&&(s.terminalCompleted.includes(id)||(s.unlocked.includes(id)&&(id===0||s.terminalCompleted.includes(id-1))));}
export function nextTerminal(s){return [0,1,2,3,4,5].find(id=>!s.terminalCompleted.includes(id)&&terminalAvailable(s,id));}
export function claimTerminal(s,id){if(!terminalAvailable(s,id)||s.terminalCompleted.includes(id))return false;s.terminalCompleted.push(id);s.energy+=WORKSTATION_REWARDS[id];s.shards++;s.xp+=50;return true;}
export function openSector(s,i){if(!canUnlock(s,i))return false;s.shards-=SECTORS[i].cost;s.energy-=SITE_COMPONENTS[i];s.installedModules.push(i);s.unlocked.push(i);s.sector=i;return true;}
export function canStartUplink(s){return !s.won&&s.counts.every(n=>n>=8)&&s.terminalCompleted.length===6&&(s.installedModules.includes(6)||availableModules(s)>0&&s.energy>=300);}
export function startUplink(s){if(!canStartUplink(s))return false;if(!s.installedModules.includes(6)){s.installedModules.push(6);s.energy-=300;}return true;}
