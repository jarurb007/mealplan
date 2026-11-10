const $=s=>document.querySelector(s);
let S=null,preview=null,tab='plan',viewWeek=null,scrolled=false,showArch=false,openSrv={},openRec={},openIng={},openStp={},openAIng={},pollT=null,
  lang=localStorage.getItem('lang')||(/^(nb|no|nn)/i.test(navigator.language)?'no':/^pl/i.test(navigator.language)?'pl':(/^en/i.test(navigator.language)?'en':'no'));
const t=k=>(L[lang][k]??L.no[k]??k);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const okUrl=u=>/^https?:\/\//i.test(String(u??''));   // źródło przepisu jako odnośnik tylko dla http(s) (nie javascript:)
const nm=n=>lang==='no'?n:((S&&S.trmap&&S.trmap[lang]&&S.trmap[lang][String(n).toLowerCase()])||n);
const mv=m=>{const x=lang!=='no'&&m.tr&&m.tr[lang];return x?{name:x.name,description:x.description,ing:x.ingredients,steps:x.steps}:{name:m.name,description:m.description,ing:m.ingredients.map(i=>i.name),steps:m.steps}};
const dm=d=>d.slice(8)+'.'+d.slice(5,7);
const wq=()=>viewWeek?`?week=${viewWeek}`:'';
const W=o=>viewWeek?{...o,week:viewWeek}:o;
function toast(x){const e=$('#toast');e.textContent=x;e.style.display='block';setTimeout(()=>e.style.display='none',3500)}
/* --- zapis zmian: kolejka mutacji. Każda akcja czeka na poprzednią i żadna nie przepada (dawniej akcja kliknięta
   w trakcie innej była po cichu pomijana). Ekran przygasa i pokazuje żółty pasek tylko przy długich operacjach
   z modelem, czyli tych, które podają msg; krótkie akcje nie blokują interfejsu.
   pending = akcje czekające lub w toku; mutSeq rośnie po każdej zakończonej (po tym poznajemy nieświeży stan z tła). */
let queue=Promise.resolve(),pending=0,mutSeq=0,longOps=0,lastAct=null;
function busyBar(msg){const bb=$('#busybar');document.body.classList.toggle('spin',!!msg);
  if(msg)bb.textContent='⏳ '+msg;bb.style.display=msg?'block':'none'}
function send(path,method='POST',body,msg){
  pending++;if(msg){longOps++;busyBar(msg)}
  const run=async()=>{
    try{const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
      if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||r.statusText)}
      return await r.json()}
    finally{pending--;mutSeq++;if(msg&&!--longOps)busyBar('')}};
  const p=queue.then(run);queue=p.catch(()=>{});return p}
async function api(path,method='POST',body,msg){
  const me={key:method+' '+path+' '+JSON.stringify(body??null)};
  if(lastAct&&lastAct.key===me.key)return;   // ta sama akcja kliknięta drugi raz, zanim pierwsza się wykonała: nie dublujemy
  lastAct=me;
  try{return await send(path,method,body,msg)}
  catch(e){toast(t('err')+e.message);recover()}
  finally{if(lastAct===me)lastAct=null}}
// Akcja się nie udała, a ekran mógł już pokazywać coś, czego serwer nie zapisał (zaznaczone pole, wybrany dzień):
// wracamy do stanu z serwera, a gdy serwer nie odpowiada, do ostatniego znanego.
async function recover(){forceRender=true;if(pending)return;if(!await refreshQuiet()&&S)render()}
// Stan z serwera. Jeśli w trakcie pobierania skończyła się jakaś akcja, odpowiedź może być sprzed niej: pobieramy jeszcze raz.
async function fetchState(){for(;;){const seq=mutSeq;const r=await fetch('/api/state'+wq());if(!r.ok)throw new Error(r.statusText);
  const d=await r.json();if(seq===mutSeq)return d}}
let custOpen=false,custText='',custImgs=[];
let sec={};try{sec=JSON.parse(localStorage.getItem('sec')||'{}')}catch(e){}
function foldSec(k){sec[k]=!sec[k];localStorage.setItem('sec',JSON.stringify(sec));render()}
function secHead(k,icon,title,cnt,sub,extra){return `<div class="sechead" data-click="foldSec" data-k="${k}"><b>${icon} ${title}</b>${cnt?`<span class="cnt">${cnt}</span>`:''}<span class="sub">${sec[k]?'':esc(sub||'')}</span>${extra||''}<span class="chev">${sec[k]?'▾':'▸'}</span></div>`}
function toggleCust(){custOpen=!custOpen;if(custOpen){sec.book=true;localStorage.setItem('sec',JSON.stringify(sec))}render()}
function custPanel(){return `<div class="alt" style="margin-top:8px"><b>${t('custTitle')}</b><div class="desc">${t('custHint')}</div>
  <textarea id="ct" rows="5" placeholder="${esc(t('custPh'))}" data-input="custText" style="margin-top:6px">${esc(custText)}</textarea>
  <div class="row"><label class="b" style="cursor:pointer">📷 ${t('custTake')}<input id="camIn" type="file" accept="image/*" capture="environment" style="display:none" data-change="addImgs"></label>
  <label class="b" style="cursor:pointer">🖼 ${t('custPick')}<input id="galIn" type="file" accept="image/*" multiple style="display:none" data-change="addImgs"></label>
  <span class="desc">${custImgs.length}/4</span></div>
  ${custImgs.length?`<div class="row">${custImgs.map((u,i)=>`<div style="position:relative"><img src="${u}" alt="" style="height:84px;border-radius:8px;border:1px solid var(--bd)"><a href="#" data-click="rmImg" data-i="${i}" style="position:absolute;top:-6px;right:-6px;background:var(--card);border:1px solid var(--bd);border-radius:50%;width:22px;height:22px;text-align:center;line-height:20px;text-decoration:none;color:var(--del)">✕</a></div>`).join('')}</div>`:''}
  <div class="row"><button class="b p" data-click="sendCust">${t('custAdd')}</button><button class="b" data-click="custCancel">${t('cancel')}</button></div></div>`}
async function shrink(file){const url=URL.createObjectURL(file);try{const img=new Image();
  await new Promise((ok,no)=>{img.onload=ok;img.onerror=no;img.src=url});
  const sc=Math.min(1,1600/Math.max(img.width,img.height));const c=document.createElement('canvas');
  c.width=Math.round(img.width*sc);c.height=Math.round(img.height*sc);
  const x=c.getContext('2d');x.fillStyle='#fff';x.fillRect(0,0,c.width,c.height);x.drawImage(img,0,0,c.width,c.height);
  return c.toDataURL('image/jpeg',0.82)}finally{URL.revokeObjectURL(url)}}
async function addImgs(files){for(const f of Array.from(files)){if(custImgs.length>=4){toast(t('custMax'));break}
  try{custImgs.push(await shrink(f))}catch(e){toast(t('custBadImg'))}}render()}
function rmImg(i){custImgs.splice(i,1);render()}
async function sendCust(){if(!custText.trim()&&!custImgs.length){toast(t('custNeed'));return}
  const r=await api('/api/recipes/custom','POST',{text:custText,images:custImgs},t('custReading'));
  if(r){custText='';custImgs=[];custOpen=false;set(r);toast('⭐ '+t('custSaved'))}}
let initDone=false;
async function load(){adopt(await fetchState());if(!viewWeek)scrolled=false;
  if(!initDone){initDone=true;if(shouldOpenWizard(S))goTab('fridge')}
  render();ensureTr()}
function set(r){if(!r||r.meals===undefined)return;
  mutSeq++;
  if(pending)return;   // w kolejce czekają następne akcje: ekran odświeży odpowiedź ostatniej (stan pośredni tylko by mignął)
  const prevA=S?S.shop_alert||0:0;if((r.shop_alert||0)>prevA)setTimeout(()=>toast('🛒 '+t('shopChanged')),50);
  // odpowiedź dotyczy innego tygodnia niż oglądany (np. ktoś zdążył przejść dalej, zanim akcja wróciła): pokaż oglądany
  if(r.week&&r.week.id!==(viewWeek||r.current_id)){load();return}
  adopt(r);render();ensureTr()}
const UIF=['open','hint','loading','choosing','justReady','closing'];
function adopt(d){if(S&&S.meals&&d&&d.meals){const old=new Map(S.meals.map(m=>[m.id,m]));
  d.meals.forEach(n=>{const o=old.get(n.id);if(!o)return;UIF.forEach(k=>{if(o[k]!==undefined)n[k]=o[k]});
    if(o.closing){n.alts=null;n.open=false}
    else if(o.alts&&o.alts.length&&(!n.alts||n.alts.length===0))n.alts=o.alts})}
  S=d}
const trTried={};
async function ensureTr(){
  if(lang==='no'||!S||!S.week)return;
  if(!S.meals.some(m=>!(m.tr&&m.tr[lang])))return;
  const wk=S.week.id,lg=lang,key=lg+':'+S.meals.map(m=>m.id+'.'+m.steps.length+'.'+(m.draft?1:0)).join(',');
  if(trTried[key])return;trTried[key]=1;
  const tb=$('#trbar');tb.textContent='🌐 '+t('bTr');tb.style.display='block';const seq=mutSeq;
  try{const r=await fetch('/api/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lang:lg,week:wk})});
    if(r.ok){const d=await r.json();if(!pending&&seq===mutSeq&&!drag&&S.week&&S.week.id===d.week.id){adopt(d);render()}else if(S&&S.week&&S.week.id===d.week.id){S.trmap=d.trmap;S.meals.forEach(m=>{const n=d.meals.find(x=>x.id===m.id);if(n)m.tr=n.tr})}}}
  catch(e){}finally{tb.style.display='none'}}
function setLang(l){lang=l;localStorage.setItem('lang',l);document.documentElement.lang=l;
  document.querySelectorAll('.lang button').forEach(b=>b.classList.toggle('on',b.dataset.l===l));
  $('#n_plan').textContent=t('tabP');$('#n_shop').textContent=t('shop');$('#n_fridge').textContent=t('tabW');
  if(S){render();ensureTr()}}
document.querySelectorAll('.lang button').forEach(b=>b.onclick=()=>setLang(b.dataset.l));
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>goTab(b.dataset.t));
$('#gear').onclick=()=>{const g=$('#gearbox');g.style.display=g.style.display==='flex'?'none':'flex';gearRender()};
$('#themeBtn').onclick=()=>toggleTheme();
/* --- zdarzenia: jeden zestaw listenerów na dokumencie (delegacja). Element niesie nazwę akcji w data-click,
   data-change, data-enter albo data-input, a parametry w pozostałych data-*. Dane (nazwy dań, klucze produktów)
   są więc zawsze tekstem w atrybucie, nigdy fragmentem kodu JS sklejanym w atrybucie zdarzenia. */
const byId=f=>d=>f(+d.id);
const numOrNull=v=>v===''||v==null?null:+v;
const ACT={
 click:{
  foldSec:d=>foldSec(d.k),toggleCust:()=>toggleCust(),sendCust:()=>sendCust(),custCancel:()=>{custOpen=false;render()},rmImg:d=>rmImg(+d.i),
  setDef:d=>setDef(+d.n),undislike:byId(undislike),pickWeek:byId(pickWeek),
  st:d=>st(+d.id,d.s),restoreSwap:d=>st(+d.id,'planned').then(()=>openAlt(+d.id)),
  retryRec:byId(retryRec),toggleIng:byId(toggleIng),toggleRec:byId(toggleRec),toggleSec:d=>toggleSec(d.w,+d.id),
  dislike:byId(dislike),fav:byId(fav),toggleSrv:byId(toggleSrv),srv:d=>srv(+d.id,numOrNull(d.n)),
  openAlt:byId(openAlt),removeDay:byId(removeDay),carry:byId(carry),
  goTab:d=>goTab(d.t),goWeek:d=>goWeek(numOrNull(d.id)),confirmPlan:()=>confirmPlan(),delWeek:byId(delWeek),confirmWeek:byId(confirmWeek),
  findAlts:d=>findAlts(+d.id,false),closeAlt:byId(closeAlt),toggleAIng:d=>toggleAIng(d.k),choose:d=>choose(+d.id,+d.i),
  togUses:d=>togUses(d.k),addX:()=>addX(),delX:byId(delX),dismissG:d=>dismissG(d.k),
  copyList:()=>copyList(),addP:()=>addP(),delP:byId(delP),addC:()=>addC(),delC:byId(delC),delRec:byId(delRec),gen:()=>gen(),jbAdd:()=>jbAdd()},
 change:{
  done:(d,el)=>st(+d.id,el.checked?'done':'planned'),mv2:(d,el)=>mv2(+d.id,el.value),chk:(d,el)=>chk(d.k,el.checked),
  takeRec:(d,el)=>takeRec(+d.id,el.checked),setDay:(d,el)=>setDay(d.kind,+d.id,el.value),addImgs:(d,el)=>{addImgs(el.files);el.value=''}},
 enter:{findAlts:d=>findAlts(+d.id,false),addX:()=>addX(),addP:()=>addP(),addC:()=>addC(),jbAdd:()=>jbAdd()},
 input:{custText:(d,el)=>{custText=el.value}}};
function dispatch(kind,e){
  const el=e.target&&e.target.closest?e.target.closest('[data-'+kind+']'):null;if(!el)return;
  const name=el.dataset[kind];if(!Object.prototype.hasOwnProperty.call(ACT[kind],name))return;
  if(kind==='click'&&(el.tagName==='A'||el.tagName==='BUTTON'))e.preventDefault();   // <a href="#"> nie przewija strony, przycisk w <label> nie przełącza pola
  ACT[kind][name](el.dataset,el)}
document.addEventListener('click',e=>dispatch('click',e));
document.addEventListener('change',e=>dispatch('change',e));
document.addEventListener('input',e=>dispatch('input',e));
document.addEventListener('keydown',e=>{if(e.key==='Enter')dispatch('enter',e)});
function gearRender(){if(!S)return;const dl=S.dislikes||[];$('#gearbox').innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center;width:100%"><span>${t('pDef')}</span><span><button class="b" style="padding:3px 10px" data-click="setDef" data-n="${S.servings_default-1}">−</button> <b style="padding:0 8px">${S.servings_default}</b> <button class="b" style="padding:3px 10px" data-click="setDef" data-n="${S.servings_default+1}">+</button></span></div>
  <div style="width:100%;margin-top:10px"><b>👎 ${t('dislikesT')}</b> <span style="opacity:.8">${t('dislikesSub')}</span>
  ${dl.length?dl.map(d=>`<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #ffffff33"><span>${esc(d.name)}${d.reason?` <i style="opacity:.75">– ${esc(d.reason)}</i>`:''}</span><button class="gear" aria-label="${esc(t('restore'))}" data-click="undislike" data-id="${d.id}">✕</button></div>`).join(''):`<div style="opacity:.75;padding:4px 0">${t('dislikesNone')}</div>`}</div>`}
let wbKey='';
function isoWk(ds){const x=new Date(ds+'T12:00:00');x.setDate(x.getDate()+2);const d=new Date(Date.UTC(x.getFullYear(),x.getMonth(),x.getDate()));const n=d.getUTCDay()||7;d.setUTCDate(d.getUTCDate()+4-n);const y=new Date(Date.UTC(d.getUTCFullYear(),0,1));return Math.ceil(((d-y)/864e5+1)/7)}
function weekBar(){const bar=$('#weekbar');if(!S||!(S.weeks||[]).length){bar.style.display='none';return}
  bar.style.display='flex';const prev=bar.scrollLeft;
  const ws=[...S.weeks].sort((a,b)=>a.start<b.start?-1:1);
  bar.innerHTML=ws.map(w=>`<button class="wk ${w.id===S.current_id?'cur':''} ${S.week&&w.id===S.week.id?'on':''}" data-id="${w.id}" data-click="pickWeek"><b>${t('wk')}${isoWk(w.start)}</b><span>${dm(w.start)}</span></button>`).join('');
  const key=ws.map(w=>w.id).join(',')+'|'+S.current_id;
  if(key!==wbKey){wbKey=key;requestAnimationFrame(()=>{const c=bar.querySelector('.wk.cur');if(c)bar.scrollLeft=c.offsetLeft-bar.clientWidth/2+c.offsetWidth/2})}
  else bar.scrollLeft=prev}
function pickWeek(id){if(S&&S.week&&id===S.week.id)return;goWeek(id===S.current_id?null:id)}
let mainHtml=null,forceRender=false;
function render(){
  const keep={};document.querySelectorAll('#main input[type=text],#main input:not([type])').forEach(e=>{if(e.id)keep[e.id]=e.value});
  const ae=document.activeElement,aid=ae&&ae.id,as=ae&&ae.selectionStart;
  $('#range').textContent=S.week?`${dm(S.week.start)} – ${dm(S.week.end)}${S.week.id!==S.current_id?' · '+(S.week.start>S.today?t('upcoming'):t('archBan')).replace(':',''):''}`:'';
  gearRender();weekBar();
  $('#n_shop').textContent=t('shop')+((S.shop_alert||0)>0?' ●':'');
  // Listę przebudowujemy tylko wtedy, gdy jej treść się zmieniła. Odświeżenie w tle, które nic nie zmienia, nie podmienia
  // więc elementu pod palcem (dotknięcie trwające w chwili podmiany przepadało). forceRender wymusza przebudowę,
  // gdy trzeba cofnąć coś, co zmieniło się tylko na ekranie (zaznaczone pole po nieudanym zapisie).
  const html=tab==='plan'?plan():tab==='shop'?shop():fridge();
  if(html!==mainHtml||forceRender){forceRender=false;mainHtml=html;
    $('#main').innerHTML=html;
    for(const [id,v] of Object.entries(keep)){const e=document.getElementById(id);if(e&&!e.value)e.value=v}
    if(aid){const e=document.getElementById(aid);if(e){e.focus();try{e.setSelectionRange(as,as)}catch(_){}}}}
  if(tab==='plan'&&!scrolled){scrolled=true;const td=document.querySelector('.slot.today');if(td)setTimeout(()=>td.scrollIntoView({block:'start',behavior:'smooth'}),60)}
  if(tab==='fridge')wizSync();
  schedulePoll()}
function needPoll(){return S&&S.meals&&S.meals.some(m=>m.filling||(m.alts&&m.alts.length===0&&!m.loading))}
function schedulePoll(){if(pollT||!needPoll())return;pollT=setTimeout(async()=>{pollT=null;if(drag||pending){schedulePoll();return}
  const seq=mutSeq;
  try{const r=await fetch('/api/state'+wq());if(r.ok){const d=await r.json();
    if(drag||pending||seq!==mutSeq){schedulePoll();return}   // w trakcie pobierania poszła akcja: ta odpowiedź może być sprzed niej
    const waiting=new Set(S.meals.filter(m=>m.alts&&m.alts.length===0).map(m=>m.id));
    adopt(d);const ready=d.meals.filter(m=>waiting.has(m.id)&&m.alts&&m.alts.length>0).map(m=>m.id);
    render();ready.forEach(attention);return}}catch(e){}render()},2500)}
function ingList(names){return `<ul>${names.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`}
function mealCard(m){const v=mv(m),D=t('days');const isToday=m.date===S.today;
  if(m.status==='removed')return `<div class="meal off" data-id="${m.id}">
   <div class="mh"><span class="offtxt">🚫 ${t('dayOff')}</span><span class="handle">⠿</span></div>
   <div class="desc" style="text-decoration:line-through">${esc(v.name)}</div>
   <div class="row"><button class="b" data-click="st" data-id="${m.id}" data-s="planned">↺ ${t('restore')}</button>
    <button class="b" data-click="restoreSwap" data-id="${m.id}">🔄 ${t('otherDish')}</button></div>
   <div id="alt${m.id}">${m.open?altsHtml(m):''}</div></div>`;
  const sOpen=openSrv[m.id];
  const tags=`${m.is_fish?`<span class="tag">${t('fish')}</span>`:''}${m.status==='skipped'?`<span class="tag">${t('tSkip')}</span>`:''}${m.owned?`<span class="tag">${t('tCarry')}</span>`:''}`;
  let chip,panel='';
  if(m.draft){
    const iOpen=!!openIng[m.id];
    if(m.filling)chip=`<button class="srv chip on" disabled>⏳ ${t('recWait')}</button>`;
    else if(m.draft_error)chip=`<button class="srv chip" style="background:var(--badbg);color:var(--bad)" data-click="retryRec" data-id="${m.id}">${t('recFail')}</button>`;
    else chip=`<button class="srv chip ${iOpen?'on':''}" data-click="toggleIng" data-id="${m.id}">🧾 ${t('ingChip')} ${iOpen?'▴':'▾'}</button>`;
    if(iOpen&&!m.filling&&!m.draft_error)panel=`<div class="rec">${ingList(m.ingredient_names||[])}</div>`;
  }else{
    const rOpen=openRec[m.id]??(isToday&&m.status==='planned');
    chip=`<button class="srv chip ${rOpen?'on':''}" data-click="toggleRec" data-id="${m.id}">📖 ${t('recipe')} ${rOpen?'▴':'▾'}</button>`;
    if(rOpen){const iO=openIng[m.id]??true,sO=openStp[m.id]??true;
      panel=`<div class="rec"><a href="#" class="sec" data-click="toggleSec" data-w="ing" data-id="${m.id}"><b>${t('sectIng')}</b> ${iO?'▴':'▾'}</a>
       ${iO?`<ul>${m.ingredients.map((i,k)=>`<li>${esc(m.qv[k]??'')} ${esc(i.unit)} ${esc(v.ing[k]||i.name)}</li>`).join('')}</ul>`:''}
       <a href="#" class="sec" data-click="toggleSec" data-w="stp" data-id="${m.id}"><b>${t('sectStp')}</b> ${sO?'▴':'▾'}</a>
       ${sO?`<ol>${v.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol>`:''}
       ${okUrl(m.source)?`<div class="desc"><a href="${esc(m.source)}" target="_blank" rel="noopener">${t('src')}</a></div>`:''}</div>`}
  }
  // szkic bez przepisu w zatwierdzonym tygodniu, którego nikt nie pisze (np. przywrócony dzień, restart serwera w trakcie pisania)
  const stuck=m.draft&&!m.filling&&!m.draft_error&&S.week.confirmed;
  const showAlt=m.open||(m.alts&&m.alts.length>=0&&m.alts!==null);
  return `<div class="meal ${m.status!=='planned'?'done':''}" data-id="${m.id}">
   <div class="mh"><input type="checkbox" class="chk" ${m.status==='done'?'checked':''} data-change="done" data-id="${m.id}" aria-label="done">
    <button class="ic ${m.disliked?'on':''}" data-click="dislike" data-id="${m.id}" aria-label="dislike" title="${esc(t('dislikeT'))}">👎</button>
    <button class="ic ${m.fav?'on':''}" data-click="fav" data-id="${m.id}" aria-label="favorite">⭐</button>
    <span class="handle">⠿</span></div>
   <div class="name">${esc(v.name)}</div>
   <div class="desc">${esc(v.description)}${m.time_min?` · ${esc(m.time_min)} min`:''}${tags}</div>
   <div class="row" style="flex-wrap:nowrap;justify-content:space-between">${chip}
    <button class="srv" data-click="toggleSrv" data-id="${m.id}">👥 ${m.servings_eff} ${t('por')} ✎</button></div>
   ${sOpen?`<div class="row"><span>👥 <button class="b" style="padding:5px 11px" data-click="srv" data-id="${m.id}" data-n="${m.servings_eff-1}">−</button> <b style="padding:0 6px">${m.servings_eff}</b> <button class="b" style="padding:5px 11px" data-click="srv" data-id="${m.id}" data-n="${m.servings_eff+1}">+</button>${m.servings?` <a href="#" data-click="srv" data-id="${m.id}" data-n="">↺</a>`:''}</span></div>`:''}
   ${stuck?`<div class="row"><button class="b p" data-click="retryRec" data-id="${m.id}">✍ ${t('recWrite')}</button><span class="desc">${t('recNone')}</span></div>`:''}
   ${panel}
   <div class="row">
    ${m.status==='planned'?`<button class="b" data-click="openAlt" data-id="${m.id}">🔄 ${t('swapBtn')}</button>`:''}
    <select class="b" style="flex:1;min-width:150px" data-change="mv2" data-id="${m.id}"><option value="">${t('moveBtn')}</option>${D.map((d,k)=>k===m.day?'':`<option value="${k}">${d}</option>`).join('')}</select>
    ${m.status==='planned'?`<button class="b" title="${esc(t('removeDay'))}" aria-label="${esc(t('removeDay'))}" data-click="removeDay" data-id="${m.id}">🗑</button>`:''}</div>
   <div id="alt${m.id}">${showAlt?altsHtml(m):''}</div></div>`}
function plan(){
  if(!S.week)return `<div class="card">${t('noplan')}<div class="row"><button class="b p" data-click="goTab" data-t="fridge">${t('goPlanner')}</button></div></div>`;
  const D=t('days');let h='';
  if(S.week.id!==S.current_id)h+=`<div class="warn">${S.week.start>S.today?t('upcoming'):t('archBan')} <b>${dm(S.week.start)} – ${dm(S.week.end)}</b> <div class="row"><button class="b p" data-click="goWeek" data-id="">${t('backCur')}</button></div></div>`;
  S.meals.filter(m=>m.overdue).forEach(m=>h+=`<div class="warn"><b>${D[m.day]}: ${esc(mv(m).name)}</b> ${t('overdue')}
   <div class="row"><button class="b p" data-click="st" data-id="${m.id}" data-s="done">${t('markDone')}</button>
   <button class="b" data-click="carry" data-id="${m.id}">${t('carry')}</button>
   <button class="b" data-click="st" data-id="${m.id}" data-s="skipped">${t('skip')}</button></div></div>`);
  if(S.carry.length)h+=`<div class="warn">${t('waiting')} ${S.carry.map(esc).join(', ')}</div>`;
  if(S.week.confirmed===false)h+=`<div class="warn" style="background:var(--info);border-color:var(--infobd)"><b>${t('confTitle')}</b><div class="desc" style="margin-top:4px">${t('confTxt')}</div><div class="row"><button class="b p" data-click="confirmPlan">${t('confirmBtn')}</button></div></div>`;
  h+=`<div class="desc" style="font-size:12px;margin:0 2px 8px">${t('dragHint')}</div>`;
  S.meals.forEach(m=>{const isT=m.date===S.today,past=m.date<S.today;
    h+=`<div class="slot ${isT?'today':''} ${past?'past':''} ${m.status==='removed'?'offday':''}" data-day="${m.day}"><div class="dayhead"><span class="dn">${D[m.day]}</span><span class="dd">${dm(m.date)}</span>${isT?`<span class="dt">${t('today')}</span>`:''}</div>${mealCard(m)}</div>`});
  const later=(S.weeks||[]).some(w=>w.start>S.week.start);
  if(!later)h+=`<div class="row"><button class="b" data-click="goTab" data-t="fridge">${t('goPlanner')}</button></div>`;
  h+=`<div class="row" style="margin-top:18px"><button class="b" style="color:var(--bad);border-color:var(--badbd)" data-click="delWeek" data-id="${S.week.id}">${t('delWeek')}</button></div>`;
  return h}
function altsHtml(m){const id=m.id;
  if(m.loading||(m.alts&&m.alts.length===0))return `<div class="altwrap" id="aw${id}"><div class="finding"><div class="spinner"></div><div><div class="ft">🔄 ${t('bSwap')}</div><div class="fs">${t('findSub')}</div></div></div><div class="row"><button class="b" data-click="closeAlt" data-id="${id}">${t('cancel')}</button></div><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`;
  const ask=`<input id="hint${id}" placeholder="${esc(t('askPh'))}" style="margin-top:6px" value="${esc(m.hint||'')}" data-enter="findAlts" data-id="${id}">`;
  if(!m.alts)return `<div class="altwrap" id="aw${id}"><div class="alt"><b>${t('askQ')}</b>${ask}<div class="row"><button class="b p" data-click="findAlts" data-id="${id}">${t('find')}</button><button class="b" data-click="closeAlt" data-id="${id}">${t('cancel')}</button></div></div></div>`;
  return `<div class="altwrap ${m.justReady?'ready':''}" id="aw${id}">${m.justReady?`<div class="readyb">${t('readyT')} ↓</div>`:''}`+m.alts.map((o,i)=>{const k=id+':'+i,op=!!openAIng[k];return `<div class="alt"><b>${esc(o.name)}</b><div class="desc">${esc(o.description)}</div>
  ${(o.ingredients||[]).length?`<a href="#" class="sec" data-click="toggleAIng" data-k="${k}">${op?t('hideIng')+' ▴':t('showIng')+' ▾'}</a>${op?ingList(o.ingredients):''}`:''}
  <div class="row"><button class="b p" ${m.choosing!=null?'disabled':''} data-click="choose" data-id="${id}" data-i="${i}">${m.choosing===i?'⏳':t('choose')}</button></div></div>`}).join('')+
  `<div class="alt">${ask}<div class="row"><button class="b" data-click="findAlts" data-id="${id}">${t('search')}</button><button class="b" data-click="closeAlt" data-id="${id}">${t('cancel')}</button></div></div></div>`}
function attention(id){const m=gm(id);if(!m)return;m.justReady=true;render();
  const el=document.getElementById('aw'+id);if(el)el.scrollIntoView({behavior:'smooth',block:'center'});
  toast(t('readyT'));try{navigator.vibrate&&navigator.vibrate(60)}catch(e){}
  setTimeout(()=>{const mm=gm(id);if(mm)mm.justReady=false;const e=document.getElementById('aw'+id);if(e){e.classList.remove('ready');const b=e.querySelector('.readyb');if(b)b.remove()}},4500)}
const usesOpen=new Set();
function togUses(k){usesOpen.has(k)?usesOpen.delete(k):usesOpen.add(k);render()}
function useLine(u,withQty){const m=(S.meals||[]).find(x=>x.id===u.meal);const q=withQty&&u.qty?` – ${esc(u.qty)} ${esc(u.unit)}`:'';
  return `${esc(t('days')[u.day].slice(0,3))} · ${esc(m?rv(m).name:'')}${q}`}
function usesHtml(i,k){const u=i.uses||[];if(!u.length)return '';
  if(u.length===1)return `<div class="use">${useLine(u[0])}</div>`;
  const open=usesOpen.has(k);
  return `<button type="button" class="use" data-click="togUses" data-k="${esc(k)}">${t('usedIn').replace('{n}',u.length)}: ${u.map(x=>esc(t('days')[x.day].slice(0,3))).join(', ')} ${open?'▴':'▾'}</button>`+(open?u.map(x=>`<div class="use">${useLine(x,true)}</div>`).join(''):'')}
function headsTxt(i){if(!i.heads)return '';const w=t('heads');return ` <span class="use" style="text-decoration:none">(≈ ${i.heads} ${i.heads===1?w[0]:w[1]})</span>`}
function shop(){
  if(!S.week)return '';
  let h=`<div class="shop"><div class="row" style="margin:0 0 6px"><input id="xn" placeholder="${esc(t('addPh'))}" data-enter="addX" style="flex:1"><button class="b p" data-click="addX">${t('add')}</button></div>`;
  const g=S.shopping||{};
  if(S.pending)h+=`<div class="warn">${t('shopWait')}</div>`;
  if(!Object.keys(g).length&&!S.pending)h+=`<div class="card">${t('empty')}</div>`;
  if(Object.keys(g).length)h+=`<div class="row" style="margin:0 0 6px"><button class="b" data-click="copyList">📋 ${t('copy')}</button></div>`;
  for(const [a,items] of Object.entries(g)){h+=`<h3>${esc(t(a))}</h3>`;
    items.forEach(i=>h+=`<label class="${i.checked?'c':''}"><input type="checkbox" ${i.checked?'checked':''} data-change="chk" data-k="${esc(i.key)}"><div style="flex:1;min-width:0"><span>${i.topup?'<b>+ </b>':''}${esc(i.qty)} ${esc(i.unit)} ${esc(i.extra_id?i.name:nm(i.name))}</span>${headsTxt(i)}${i.topup?` <span class="tag" style="background:var(--badbg);color:var(--bad)">${t('buyMore')}</span>`:''}${usesHtml(i,i.key)}</div>${i.extra_id?`<a href="#" data-click="delX" data-id="${i.extra_id}" style="color:var(--del);text-decoration:none;padding:0 6px">✕</a>`:''}</label>`)}
  if((S.gone||[]).length)h+=`<h3 style="color:var(--orange)">${t('goneT')}</h3>`+S.gone.map(g=>`<div class="row" style="justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line)"><span>✓ ${esc(g.label)}</span><button class="b" data-click="dismissG" data-k="${esc(g.key)}">${t('dismiss')}</button></div>`).join('');
  if(S.have.length)h+=`<h3>${t('have')}</h3>`+S.have.map(i=>`<div style="color:var(--mu);padding:4px 0">${esc(i.qty)} ${esc(i.unit)} ${esc(nm(i.name))}${usesHtml(i,'have:'+i.key)}</div>`).join('');
  return h+`</div>`}
function rv(r){const x=lang!=='no'&&r.tr&&r.tr[lang];return x?{name:x.name,description:x.description,ing:x.ingredients,steps:x.steps}:{name:r.name,description:r.description,ing:r.ingredients.map(i=>i.name),steps:r.steps}}
function daySel(kind,id,cur){const D=t('days');return `<select class="b" style="padding:4px 6px;font-size:13px" data-change="setDay" data-kind="${kind}" data-id="${id}"><option value="">${t('noDayOpt')}</option>${D.map((d,k)=>`<option value="${k}" ${cur===k?'selected':''}>${d}</option>`).join('')}</select>`}
let wizDraft=null,wizBusy=false;
function latestWeek(){return (S.weeks||[]).reduce((a,w)=>!a||w.start>a.start?w:a,null)}
async function wizSync(){const lw=latestWeek();
  if(!lw||lw.confirmed){if(wizDraft){wizDraft=null}return}
  if(wizDraft&&wizDraft.id===lw.id||wizBusy)return;
  wizBusy=true;
  try{const r=await fetch('/api/state?week='+lw.id);if(r.ok){const d=await r.json();
    wizDraft={id:lw.id,start:lw.start,end:lw.end,meals:d.meals.map(m=>({day:m.day,name:m.name,tr:m.tr}))};
    if(tab==='fridge'&&!drag)render()}}catch(e){}
  wizBusy=false}
function shouldOpenWizard(s){if(!s)return false;
  const future=(s.weeks||[]).some(w=>w.start>s.today);
  const days=Math.round((new Date(s.next_start+'T12:00:00')-new Date((s.today||s.next_start)+'T12:00:00'))/864e5);
  return !future&&days<=2}
function goTab(k){tab=k;document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x.dataset.t===k));scrolled=false;render();window.scrollTo(0,0)}
function fridge(){
  const D=t('days');
  const lw=latestWeek();const draft=lw&&!lw.confirmed?wizDraft:null;
  const target=draft?{start:draft.start,end:draft.end}:{start:S.next_start,end:(()=>{const d=new Date(S.next_start+'T12:00:00');d.setDate(d.getDate()+6);return d.toISOString().slice(0,10)})()};
  const free=S.cravings.filter(c=>!c.used);
  const picked=new Map(free.filter(c=>c.recipe_id).map(c=>[c.recipe_id,c.id]));
  const jobRunning=!!jobId;
  let h=`<div class="card" style="background:var(--wiz)"><b style="font-size:17px">🗓 ${t('wizHead')} ${t('wk')}${isoWk(target.start)} · ${dm(target.start)}–${dm(target.end)}</b>
   <div class="desc" style="margin-top:4px">${t('wizSub')}</div></div>`;
  if(lw&&!lw.confirmed){
    h+=`<div class="card" style="border:2px solid var(--ac)"><b>${t('draftT')} · ${t('wk')}${isoWk(lw.start)}</b>
    ${draft?draft.meals.map(m=>{const x=lang!=='no'&&m.tr&&m.tr[lang];return `<div class="desc" style="padding:3px 0;border-bottom:1px solid var(--line)"><b>${D[m.day]}</b> · ${esc(x?x.name:m.name)}</div>`}).join(''):`<div class="desc">…</div>`}
    <div class="row"><button class="b p" data-click="confirmWeek" data-id="${lw.id}">${t('confirmBtn')}</button><button class="b" data-click="goWeek" data-id="${lw.id===S.current_id?'':lw.id}">${t('openPlan')}</button><button class="b" style="color:var(--bad);border-color:var(--badbd)" data-click="delWeek" data-id="${lw.id}">🗑</button></div></div>`;
  }else if(lw&&lw.start>S.today){
    h+=`<div class="warn" style="background:var(--ok);border-color:var(--okbd)"><b>${t('wk')}${isoWk(lw.start)} · ${dm(lw.start)} ${t('nextReady')}</b><div class="desc">${t('nextAfter')} ${t('wk')}${isoWk(S.next_start)} · ${dm(S.next_start)}</div>
    <div class="row"><button class="b" data-click="goWeek" data-id="${lw.id}">${t('openPlan')}</button></div></div>`;
  }
  h+=`<div class="card">${secHead('pantry','🧊',t('fTitle'),S.pantry.length,S.pantry.map(p=>p.name).join(', '))}${sec.pantry?`<div class="secbody"><div class="desc" style="font-size:12px;margin-top:2px">${t('pantryHint')}</div>
   <div class="row"><input id="pn" placeholder="${esc(t('fPh'))}" data-enter="addP" style="flex:1"><button class="b p" data-click="addP">${t('add')}</button></div>
   <ul style="list-style:none;padding:0">${S.pantry.map(p=>`<li style="padding:6px 0;border-bottom:1px solid var(--line)">${esc(p.name)} <a href="#" data-click="delP" data-id="${p.id}" style="color:var(--del);text-decoration:none;padding:0 6px">✕</a></li>`).join('')}</ul></div>`:''}</div>
  <div class="card">${secHead('crav','😋',t('cTitle'),free.filter(c=>!c.recipe_id).length+picked.size,[...free.filter(c=>!c.recipe_id).map(c=>c.text),...(S.recipes||[]).filter(r=>picked.has(r.id)).map(r=>rv(r).name)].join(', '))}${sec.crav?`<div class="secbody"><div class="desc" style="font-size:12px;margin-top:2px">${t('linkHint')}</div>
   <div class="row"><input id="cn" placeholder="${esc(t('cPh'))}" data-enter="addC" style="flex:1"><button class="b p" data-click="addC">${t('add')}</button></div>
   <ul style="list-style:none;padding:0">${free.filter(c=>!c.recipe_id).map(c=>`<li style="padding:6px 0;border-bottom:1px solid var(--line)">${esc(c.text)} <a href="#" data-click="delC" data-id="${c.id}" style="color:var(--del);text-decoration:none;padding:0 6px">✕</a></li>`).join('')}</ul></div>`:''}</div>
  <div class="card">${secHead('book','⭐',t('book'),(S.recipes||[]).length,picked.size?`✓ ${picked.size}`:'',`<button class="b" style="padding:4px 9px" data-click="toggleCust">➕ ${t('custBtn')}</button>`)}${sec.book?`<div class="secbody">${custOpen?custPanel():''}${(S.recipes||[]).length?'':`<div class="desc">${t('bookEmpty')}</div>`}
  ${(S.recipes||[]).map(r=>{const v=rv(r),on=picked.has(r.id);return `<div class="alt" style="padding:6px 8px;${on?'border:2px solid var(--ac);background:var(--pick)':''}">
   <label class="rbook"><input type="checkbox" ${on?'checked':''} data-change="takeRec" data-id="${r.id}"><b style="flex:1;min-width:0">${esc(v.name)}</b></label>
   <details><summary>${t('recipe')}</summary><div class="desc">${esc(v.description)}</div>${okUrl(r.source)?`<div class="desc"><a href="${esc(r.source)}" target="_blank" rel="noopener">${t('src')}</a></div>`:''}<b>${t('ingr')}</b><ul>${r.ingredients.map((i,k)=>`<li>${esc(i.qty??'')} ${esc(i.unit)} ${esc(v.ing[k]||i.name)}</li>`).join('')}</ul><b>${t('steps')}</b><ol>${v.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol>
   <div class="row"><button class="b" style="margin-left:auto" data-click="delRec" data-id="${r.id}">${t('del')}</button></div></details></div>`}).join('')}</div>`:''}</div>
  ${draft?'':`<div class="row"><button class="b p" style="flex:1;padding:14px;font-size:16px" ${jobRunning?'disabled':''} data-click="gen">${t('goBtn')}</button></div>`}`;
  return h}
async function delWeek(wid){if(!confirm(t('delWeekQ')))return;wizDraft=null;viewWeek=null;scrolled=false;
  const r=await api('/api/week/'+wid,'DELETE');if(r){adopt(r);render();ensureTr()}}
async function confirmWeek(wid){wizDraft=null;const r=await api('/api/week/confirm','POST',{week:wid},t('jFill'));
  if(r){const jid=r.job;viewWeek=wid===r.current_id?null:wid;set(r);goTab('plan');if(jid){jobId=jid;clearTimeout(jobTimer);pollJob()}}}
async function takeRec(rid,on){const ex=S.cravings.find(c=>!c.used&&c.recipe_id===rid);
  if(on&&!ex)set(await api('/api/cravings','POST',{recipe_id:rid}));
  else if(!on&&ex)set(await api('/api/cravings/'+ex.id,'DELETE'))}
async function goWeek(id){viewWeek=id;scrolled=false;tab='plan';await load()}
let jobTimer=null,jobId=null;
let jbBuilt=false;
function jobBar(j){const b=$('#jobbar');if(!j){b.style.display='none';jbBuilt=false;return}
  const total=j.total||7,done=j.done||0,fill=j.kind==='fill',pct=(!fill&&j.stage==='plan')?8:Math.round(fill?(done/total*100):10+90*done/total);
  if(!jbBuilt){b.innerHTML=`<div id="jb_t"></div><div class="pb"><i id="jb_p"></i></div><div class="nm" id="jb_n"></div>
    <div class="row" style="flex-wrap:nowrap;margin-top:8px"><input id="jb_i" placeholder="${esc(t('addNow'))}" style="flex:1;padding:7px;font-size:14px" data-enter="jbAdd"><button class="b p" data-click="jbAdd">+</button></div>`;jbBuilt=true}
  $('#jb_t').textContent='⏳ '+((!fill&&j.stage==='plan')?t('jPlan'):t(fill?'jFill':'jRec')+' '+done+'/'+total);
  $('#jb_p').style.width=pct+'%';
  const nm=(j.ready||[]).slice(-1)[0]||'';$('#jb_n').textContent=nm?'✓ '+nm:t('jBg');
  b.style.display='block'}
async function jbAdd(){const i=$('#jb_i'),v=(i.value||'').trim();if(!v)return;i.value='';
  try{const r=await fetch('/api/shop/extra',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(W({name:v}))});
    if(r.ok){const d=await r.json();mutSeq++;if(!pending&&S&&S.week&&d.week&&S.week.id===d.week.id){adopt(d);if(tab==='shop')render()}toast(t('addedT')+v)}}catch(e){}}
async function pollJob(){
  try{const r=await fetch(jobId?`/api/job/${jobId}`:'/api/job');const d=await r.json();const j=jobId?d:d.job;
    if(!j){stopJob();return}
    jobId=j.id;jobBar(j);
    if(j.status==='done'){stopJob();const b=$('#jobbar');b.innerHTML=`<div>${t('jDone')}</div>`;b.style.display='block';jbBuilt=false;setTimeout(()=>{if(!jobId&&!jbBuilt)b.style.display='none'},2500);
      if(j.error)toast(t('jErr')+j.error);
      if(j.kind==='fill'){await refreshQuiet()}else{viewWeek=(j.week_id&&j.week_id!==(S&&S.current_id))?j.week_id:null;await load();goTab('plan')}return}
    if(j.status==='error'){stopJob();toast(t('jErr')+(j.error||''));return}
  }catch(e){}
  jobTimer=setTimeout(pollJob,1500)}
async function refreshQuiet(){try{adopt(await fetchState());render();ensureTr();return true}catch(e){return false}}
function stopJob(){clearTimeout(jobTimer);jobTimer=null;jobId=null;jbBuilt=false}
async function gen(){const r=await fetch('/api/week/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!r.ok){const e=await r.json().catch(()=>({}));toast(t('err')+(e.detail||r.statusText));return}
  const d=await r.json();jobId=d.job;clearTimeout(jobTimer);pollJob()}
async function st(id,s){set(await api(`/api/meal/${id}/status`,'POST',{status:s}))}
async function removeDay(id){if(!confirm(t('removeDayQ')))return;await st(id,'removed')}
async function dislike(id){const m=gm(id);if(!m)return;
  if(m.disliked){set(await api(`/api/meal/${id}/dislike`,'POST',{reason:''}));toast(t('dislikeOff'));return}
  const why=prompt(t('dislikeQ'),'');if(why===null)return;
  const r=await api(`/api/meal/${id}/dislike`,'POST',{reason:why});if(!r)return;set(r);
  const mm=gm(id);if(mm&&mm.status!=='removed'&&confirm(t('dislikeSwap')))openAlt(id)}
async function undislike(did){set(await api(`/api/dislikes/${did}`+(viewWeek?`?week=${viewWeek}`:''),'DELETE'))}
async function fav(id){const r=await api(`/api/meal/${id}/favorite`);if(r){const m=r.meals.find(x=>x.id===id);set(r);if(m&&m.fav)toast('⭐ '+t('favOn'))}}
async function carry(id){set(await api(`/api/meal/${id}/carry`))}
function toggleIng(id){openIng[id]=!openIng[id];render()}
function toggleAIng(k){openAIng[k]=!openAIng[k];render()}
function toggleSec(w,id){const mm=w==='ing'?openIng:openStp;mm[id]=!(mm[id]??true);render()}
async function confirmPlan(){const r=await api('/api/week/confirm','POST',W({}),t('jFill'));if(r){const jid=r.job;set(r);if(jid){jobId=jid;clearTimeout(jobTimer);pollJob()}}}
async function retryRec(id){set(await api(`/api/meal/${id}/recipe`))}
function toggleRec(id){const m=S.meals.find(x=>x.id===id);const cur=openRec[id]??(m.date===S.today&&m.status==='planned');openRec[id]=!cur;render()}
function toggleSrv(id){openSrv[id]=!openSrv[id];render()}
async function setDef(n){if(n<1||n>12)return;set(await api('/api/settings','POST',{servings:n}))}
async function srv(id,n){if(n!==null&&(n<1||n>12))return;set(await api(`/api/meal/${id}/servings`,'POST',{servings:n}))}
function openAlt(id){const m=gm(id);m.open=true;m.alts=null;m.loading=false;m.closing=false;render()}
const altReq={};let altSeq=0;   // numer trwającego szukania dla dania; „Anuluj” go kasuje, więc spóźniona odpowiedź nie otwiera propozycji z powrotem
async function clearAlts(id){try{await fetch(`/api/meal/${id}/alts/clear`,{method:'POST'})}catch(e){}}
async function closeAlt(id){const m=gm(id);if(!m)return;
  const running=altReq[id]!=null;delete altReq[id];
  m.open=false;m.alts=null;m.hint='';m.loading=false;m.closing=true;render();
  await clearAlts(id);
  if(running)return;   // serwer jeszcze szuka i na koniec zapisze propozycje: posprząta po nich findAlts, gdy wróci odpowiedź
  const mm=gm(id);if(mm)mm.closing=false}
const gm=id=>S.meals.find(x=>x.id===id);
async function findAlts(id,surprise){let m=gm(id);if(!m)return;
  const hint=(($('#hint'+id)||{}).value||'').trim();m.hint=hint;m.loading=true;m.justReady=false;m.alts=null;render();
  const lb=document.getElementById('aw'+id);if(lb)lb.scrollIntoView({behavior:'smooth',block:'nearest'});
  let good=false,opts=null;const tk=altReq[id]=++altSeq;
  try{const r=await fetch(`/api/meal/${id}/alternatives`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hint,count:3})});
    if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||r.statusText)}
    opts=(await r.json()).options;good=true}catch(e){if(altReq[id]===tk)toast(t('err')+e.message)}
  if(altReq[id]!==tk){   // anulowane w trakcie szukania
    if(altReq[id]==null){await clearAlts(id);const mm=gm(id);if(mm)mm.closing=false}
    return}
  delete altReq[id];
  m=gm(id);if(!m){return}
  m.loading=false;if(good){m.alts=opts;m.open=true;attention(id)}else{m.alts=null;render()}}
async function choose(id,i){let m=gm(id);m.choosing=i;render();
  const nm=m.alts&&m.alts[i]?m.alts[i].name:null;
  try{const r=await fetch(`/api/meal/${id}/choose`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i,name:nm})});
    if(!r.ok){const e=await r.json().catch(()=>({}));if(r.status===409){const mm=gm(id);if(mm){mm.choosing=null;mm.alts=null;mm.open=false}await refreshQuiet()}throw new Error(e.detail||r.statusText)}
    const d=await r.json();const mm=gm(id);if(mm)mm.choosing=null;set(d)}catch(e){const mm=gm(id);if(mm)mm.choosing=null;toast(t('err')+e.message);render()}}
async function mv2(id,d){if(d==='')return;set(await api(`/api/meal/${id}/move`,'POST',{day:+d}))}
async function addP(){const v=$('#pn').value;if(!v.trim())return;set(await api('/api/pantry','POST',{name:v}))}
async function delP(id){set(await api('/api/pantry/'+id,'DELETE'))}
async function addC(){const v=$('#cn').value.trim();if(!v)return;const isU=/^https?:\/\/\S+$/i.test(v);
  const r=await api('/api/cravings','POST',{text:v},isU?t('bImport'):undefined);if(r){set(r);if(isU)toast('⭐ '+t('favOn'))}}
async function pickRec(id){if(!id)return;set(await api('/api/cravings','POST',{recipe_id:+id}));tab='fridge';render()}
async function delC(id){set(await api('/api/cravings/'+id,'DELETE'))}
async function delRec(id){set(await api('/api/recipes/'+id,'DELETE'))}
async function useRec(id,d){if(d==='')return;const r=await api(`/api/recipes/${id}/use`,'POST',W({day:+d}));if(r){set(r);tab='plan';scrolled=true;render()}}
async function setDay(kind,id,v){set(await api(`/api/${kind==='c'?'cravings':'pantry'}/${id}/day`,'POST',{day:v===''?null:+v}))}
async function applyP(){const r=await api('/api/pantry/preview','POST',W({}),t('bFit'));if(r){preview=r;render()}}
async function commitP(){const r=await api('/api/pantry/commit','POST',{proposal_id:preview.proposal_id});if(r){preview=null;set(r);tab='plan';scrolled=false;render()}}
async function addX(){const v=$('#xn').value;if(!v.trim())return;set(await api('/api/shop/extra','POST',W({name:v})))}
async function delX(id){set(await api('/api/shop/extra/'+id,'DELETE'))}
async function dismissG(k){set(await api('/api/shop/dismiss','POST',W({key:k})))}
/* Odhaczanie zakupów: pole zmienia się od razu, zapis idzie kolejką w tle (jedno zapytanie na kliknięcie).
   Gdy zapis się nie uda, pole wraca do stanu potwierdzonego przez serwer i pojawia się komunikat z nazwą produktu. */
const chkWait=new Map();   // klucz produktu -> {base: stan potwierdzony przez serwer, n: ile zapisów tego produktu jest jeszcze w drodze}
function shopItem(k){for(const g of Object.values((S&&S.shopping)||{})){const i=g.find(x=>x.key===k);if(i)return i}return null}
async function chk(k,c){
  const it=shopItem(k),w=chkWait.get(k)||{base:it?!!it.checked:!c,n:0};w.n++;chkWait.set(k,w);
  if(it)it.checked=c;render();
  try{const r=await send('/api/shop/check','POST',W({key:k,checked:c}));w.base=c;
    if(r&&r.meals!==undefined)set(r);     // backend zwraca pełny stan, jak inne endpointy
    else if(!pending)refreshQuiet()       // starszy backend: {"ok":true}, więc po ostatnim zapisie z serii odświeżamy stan po cichu
  }catch(e){
    const i=shopItem(k);if(i&&w.n===1)i.checked=w.base;   // cofamy dopiero, gdy żaden nowszy zapis tego produktu nie jest w drodze
    forceRender=true;render();
    toast(t('chkFail').replace('{x}',i?(i.extra_id?i.name:nm(i.name)):k));
    if(!pending)refreshQuiet()
  }finally{if(!--w.n)chkWait.delete(k)}}
async function copyList(){const x=await (await fetch('/api/shop/text?lang='+lang+(viewWeek?'&week='+viewWeek:''))).text();
  try{await navigator.clipboard.writeText(x);toast(t('copied'))}catch(e){prompt('Copy:',x)}}
/* --- drag meal card between day slots --- */
let drag=null;
function slotAt(x,y){if(!drag)return null;const c=drag.card;c.style.visibility='hidden';const el=document.elementFromPoint(x,y);c.style.visibility='';
  const sl=el&&el.closest('.slot[data-day]');return sl&&sl!==drag.slot?sl:null}
function dragLoop(){if(!drag)return;
  drag.card.style.transform=`translateY(${(drag.y-drag.y0)+(window.scrollY-drag.s0)}px)`;
  if(drag.y<130)window.scrollBy(0,-10);else if(drag.y>innerHeight-90)window.scrollBy(0,10);
  document.querySelectorAll('.slot.over').forEach(c=>c.classList.remove('over'));
  const sl=slotAt(drag.x,drag.y);if(sl)sl.classList.add('over');
  requestAnimationFrame(dragLoop)}
document.addEventListener('pointerdown',e=>{const hd=e.target.closest&&e.target.closest('.handle');if(!hd||drag)return;
  e.preventDefault();const card=hd.closest('.meal');
  drag={card,slot:card.closest('.slot'),id:+card.dataset.id,x:e.clientX,y:e.clientY,y0:e.clientY,s0:window.scrollY};
  card.classList.add('dragging');try{hd.setPointerCapture(e.pointerId)}catch(_){}
  requestAnimationFrame(dragLoop)});
document.addEventListener('pointermove',e=>{if(drag){drag.x=e.clientX;drag.y=e.clientY;e.preventDefault()}},{passive:false});
function endDrag(e,cancel){if(!drag)return;const d=drag;const sl=cancel?null:slotAt(e.clientX,e.clientY);drag=null;
  d.card.classList.remove('dragging');d.card.style.transform='';
  document.querySelectorAll('.slot.over').forEach(c=>c.classList.remove('over'));
  if(sl)mv2(d.id,sl.dataset.day);else render()}
document.addEventListener('pointerup',e=>endDrag(e,false));
document.addEventListener('pointercancel',e=>endDrag(e,true));
function applyTheme(){const s=localStorage.getItem('theme');const d=s?s==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
  if(d)document.documentElement.setAttribute('data-theme','dark');else document.documentElement.removeAttribute('data-theme');
  const b=document.getElementById('themeBtn');if(b)b.textContent=d?'☀️':'🌙';
  const mt=document.querySelector('meta[name=theme-color]');if(mt)mt.content=d?'#1f4a31':'#2f7d4f'}
function toggleTheme(){const d=document.documentElement.getAttribute('data-theme')==='dark';localStorage.setItem('theme',d?'light':'dark');applyTheme()}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(!localStorage.getItem('theme'))applyTheme()});
applyTheme();
setLang(lang);load();pollJob();
/* --- współdzielenie: świeży stan co 15 s, gdy strona jest widoczna, i od razu po powrocie --- */
function typing(){const a=document.activeElement;return !!(a&&(a.tagName==='INPUT'||a.tagName==='TEXTAREA'||a.tagName==='SELECT')&&a.type!=='checkbox')}
function busyUI(){return pending||drag||typing()||(S&&S.meals&&S.meals.some(m=>m.loading||m.choosing!=null||m.closing))}
async function sync(){if(document.hidden||busyUI()||!S)return;
  const seq=mutSeq;
  try{const r=await fetch('/api/state'+wq());if(!r.ok)return;const d=await r.json();
    if(busyUI()||seq!==mutSeq)return;
    if(viewWeek&&!(d.weeks||[]).some(w=>w.id===viewWeek)){viewWeek=null;return load()}
    const sig=x=>JSON.stringify([x.week&&x.week.id,x.week&&x.week.confirmed,(x.weeks||[]).map(w=>w.id+':'+w.confirmed),
      (x.meals||[]).map(m=>[m.id,m.day,m.status,m.name,m.steps.length,m.servings,m.disliked,m.filling,m.alts&&m.alts.length]),
      x.shopping,x.pantry,x.cravings,(x.recipes||[]).map(r=>r.id),(x.dislikes||[]).map(r=>r.id),x.servings_default]);
    if(sig(d)===sig(S))return;
    const y=window.scrollY;adopt(d);render();window.scrollTo(0,y);ensureTr()}catch(e){}}
setInterval(sync,15000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)sync()});
window.addEventListener('focus',sync);
