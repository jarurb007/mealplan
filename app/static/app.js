const $=s=>document.querySelector(s);
let S=null,sheet=null,tab='plan',viewWeek=null,openAIng={},pollT=null,
  lang=localStorage.getItem('lang')||(/^(nb|no|nn)/i.test(navigator.language)?'no':/^pl/i.test(navigator.language)?'pl':(/^en/i.test(navigator.language)?'en':'no'));
const t=k=>(L[lang][k]??L.no[k]??k);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const okUrl=u=>/^https?:\/\//i.test(String(u??''));   // źródło przepisu jako odnośnik tylko dla http(s) (nie javascript:)
const nm=n=>lang==='no'?n:((S&&S.trmap&&S.trmap[lang]&&S.trmap[lang][String(n).toLowerCase()])||n);
const mv=m=>{const x=lang!=='no'&&m.tr&&m.tr[lang];return x?{name:x.name,description:x.description,ing:x.ingredients,steps:x.steps}:{name:m.name,description:m.description,ing:m.ingredients.map(i=>i.name),steps:m.steps}};
const dm=d=>d.slice(8)+'.'+d.slice(5,7);
const wq=()=>viewWeek?`?week=${viewWeek}`:'';
const W=o=>viewWeek?{...o,week:viewWeek}:o;
// Komunikat na dole ekranu; act = {label, fn} dodaje przycisk (np. „Cofnij”) i wydłuża czas wyświetlania.
let toastT=null,toastFn=null;
function toast(x,act){const e=$('#toast');clearTimeout(toastT);toastFn=act?act.fn:null;
  e.innerHTML=`<span>${esc(x)}</span>`+(act?`<button data-click="toastAct">${esc(act.label)}</button>`:'');
  e.style.display='block';toastT=setTimeout(()=>{e.style.display='none';toastFn=null},act?7000:3500)}
function toastAct(){const f=toastFn;toastFn=null;clearTimeout(toastT);$('#toast').style.display='none';if(f)f()}
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
function toggleCust(){custOpen=!custOpen;render()}
function custPanel(){return `<div class="alt" style="margin-top:8px"><b>${t('custTitle')}</b><div class="desc">${t('custHint')}</div>
  <textarea id="ct" rows="5" placeholder="${esc(t('custPh'))}" data-input="custText" style="margin-top:6px">${esc(custText)}</textarea>
  <div class="row"><label class="b">📷 ${t('custTake')}<input id="camIn" type="file" accept="image/*" capture="environment" style="display:none" data-change="addImgs"></label>
  <label class="b">🖼 ${t('custPick')}<input id="galIn" type="file" accept="image/*" multiple style="display:none" data-change="addImgs"></label>
  <span class="desc">${custImgs.length}/4</span></div>
  ${custImgs.length?`<div class="row">${custImgs.map((u,i)=>`<div style="position:relative"><img src="${u}" alt="" style="height:84px;border-radius:8px;border:1px solid var(--bd)"><button type="button" class="rmimg" data-click="rmImg" data-i="${i}" aria-label="${esc(t('del'))}"><span>✕</span></button></div>`).join('')}</div>`:''}
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
async function load(){adopt(await fetchState());
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
  if(S){render();ensureTr()}else{headRender();navRender()}}
/* --- zdarzenia: jeden zestaw listenerów na dokumencie (delegacja). Element niesie nazwę akcji w data-click,
   data-change, data-enter albo data-input, a parametry w pozostałych data-*. Dane (nazwy dań, klucze produktów)
   są więc zawsze tekstem w atrybucie, nigdy fragmentem kodu JS sklejanym w atrybucie zdarzenia. */
const byId=f=>d=>f(+d.id);
const numOrNull=v=>v===''||v==null?null:+v;
const ACT={
 click:{
  foldSec:d=>foldSec(d.k),toggleCust:()=>toggleCust(),sendCust:()=>sendCust(),custCancel:()=>{custOpen=false;render()},rmImg:d=>rmImg(+d.i),
  setDef:d=>setDef(+d.n),undislike:byId(undislike),weekStep:d=>weekStep(+d.d),
  openMenu:()=>openSheet({kind:'menu'}),closeSheet:()=>closeSheet(),setLang:d=>setLang(d.l),setTheme:d=>setTheme(d.th),
  toastAct:()=>toastAct(),confirmYes:()=>{const f=sheet&&sheet.fn;closeSheet();if(f)f()},
  openMeal:byId(openMeal),openRec:d=>openSheet({kind:'rec',id:+d.id}),sheetMeal:d=>openSheet({kind:'meal',id:+d.id}),toggleDone:byId(toggleDone),
  st:d=>{if(sheet&&d.s!=='planned')closeSheet();st(+d.id,d.s)},restoreSwap:d=>st(+d.id,'planned'),retryRec:byId(retryRec),
  dislikeAsk:()=>{sheet.why=true;render();const i=$('#panel input[id^=why]');if(i)i.focus()},dislikeCancel:()=>{sheet.why=false;render()},
  dislikeSave:byId(dislikeSave),dislikeOff:byId(dislikeOff),fav:byId(fav),srv:d=>srv(+d.id,numOrNull(d.n)),
  mv2:d=>{closeSheet();mv2(+d.id,d.d)},removeDay:byId(removeDay),carry:d=>{closeSheet();carry(+d.id)},
  goTab:d=>goTab(d.t),goWeek:d=>goWeek(numOrNull(d.id)),confirmPlan:()=>confirmPlan(),delWeek:byId(delWeek),confirmWeek:byId(confirmWeek),
  findAlts:d=>findAlts(+d.id),swapHint:d=>findAlts(+d.id,d.h),closeAlt:byId(closeAlt),toggleAIng:d=>toggleAIng(d.k),choose:d=>choose(+d.id,+d.i),
  togUses:d=>togUses(d.k),addX:()=>addX(),delX:byId(delX),dismissG:d=>dismissG(d.k),
  copyList:()=>copyList(),addP:()=>addP(),delP:byId(delP),addC:()=>addC(),delC:byId(delC),gen:()=>gen(),jbAdd:()=>jbAdd(),
  openBook:d=>openSheet({kind:'book',id:+d.id}),togglePick:d=>takeRec(+d.id,!bookPicked().has(+d.id)),useDay:d=>{sheet.day=+d.d;render()},
  useRec:d=>useRec(+d.id,+d.d),delRecAsk:byId(delRecAsk)},
 change:{
  chk:(d,el)=>chk(d.k,el.checked),addImgs:(d,el)=>{addImgs(el.files);el.value=''}},
 enter:{findAlts:d=>findAlts(+d.id),dislikeSave:byId(dislikeSave),addX:()=>addX(),addP:()=>addP(),addC:()=>addC(),jbAdd:()=>jbAdd()},
 input:{custText:(d,el)=>{custText=el.value},bookQ:(d,el)=>{bookQ=el.value;const b=$('#blist');if(b)b.innerHTML=bookList()}}};
function dispatch(kind,e){
  const el=e.target&&e.target.closest?e.target.closest('[data-'+kind+']'):null;if(!el)return;
  const name=el.dataset[kind];if(!Object.prototype.hasOwnProperty.call(ACT[kind],name))return;
  if(kind==='click'&&(el.tagName==='A'||el.tagName==='BUTTON'))e.preventDefault();   // <a href="#"> nie przewija strony, przycisk w <label> nie przełącza pola
  ACT[kind][name](el.dataset,el)}
document.addEventListener('click',e=>dispatch('click',e));
document.addEventListener('change',e=>dispatch('change',e));
document.addEventListener('input',e=>dispatch('input',e));
document.addEventListener('keydown',e=>{if(e.key==='Enter')dispatch('enter',e)});
/* --- arkusz od dołu: jeden kontener na menu, akcje dania, podgląd przepisu i potwierdzenia. sheet = {kind,…} albo null.
   Otwarty arkusz dokłada wpis do historii, więc systemowe „wstecz” w telefonie zamyka arkusz, a nie aplikację. */
function ovPush(){if(!(history.state&&history.state.ov))history.pushState({ov:1},'')}
function ovPop(){if(history.state&&history.state.ov)history.back()}
function openSheet(x){sheet=x;ovPush();render()}
function closeSheet(){if(!sheet)return;sheet=null;render();ovPop()}
window.addEventListener('popstate',()=>{if(sheet){sheet=null;if(S)render()}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&sheet)closeSheet()});
function sheetHead(title){return `<div class="phead"><h2>${title}</h2><button class="hb" data-click="closeSheet" aria-label="${esc(t('close'))}">✕</button></div>`}
function sheetBody(){
  if(sheet.kind==='menu')return menuHtml();
  if(sheet.kind==='confirm')return `${sheetHead(esc(sheet.title))}<p class="ptxt">${esc(sheet.text)}</p>
   <div class="row"><button class="b danger" data-click="confirmYes">${esc(sheet.yes)}</button><button class="b" data-click="closeSheet">${t('cancel')}</button></div>`;
  if(sheet.kind==='book')return bookSheet(S.recipes.find(r=>r.id===sheet.id));
  if(sheet.kind==='text')return `${sheetHead(esc(sheet.title))}<textarea rows="12" readonly>${esc(sheet.text)}</textarea>`;
  const m=gm(sheet.id);
  return sheet.kind==='rec'?recSheet(m):mealSheet(m)}
// Podmienia treść elementu tylko wtedy, gdy się zmieniła; wpisany tekst, kursor i przewinięcie zostają.
function paint(el,html,force){
  if(el._h===html&&!force)return;
  const keep={};el.querySelectorAll('input[type=text],input:not([type])').forEach(e=>{if(e.id)keep[e.id]=e.value});
  const ae=document.activeElement,aid=ae&&el.contains(ae)&&ae.id,as=aid&&ae.selectionStart,top=el.scrollTop;
  el._h=html;el.innerHTML=html;
  for(const [id,v] of Object.entries(keep)){const e=document.getElementById(id);if(e&&!e.value)e.value=v}
  if(aid){const e=document.getElementById(aid);if(e){e.focus();try{e.setSelectionRange(as,as)}catch(_){}}}
  el.scrollTop=top}
function renderSheet(){const box=$('#sheet');
  if(sheet&&(!S||((sheet.kind==='rec'||sheet.kind==='meal')&&!gm(sheet.id))||(sheet.kind==='book'&&!(S.recipes||[]).some(r=>r.id===sheet.id))))sheet=null;   // danie zniknęło (np. inny tydzień): arkusz nie ma czego pokazać
  box.classList.toggle('open',!!sheet);document.body.classList.toggle('modal',!!sheet);
  paint($('#panel'),sheet?sheetBody():'')}
function menuHtml(){const dl=S.dislikes||[],dark=document.documentElement.getAttribute('data-theme')==='dark';
  return `${sheetHead(t('menuT'))}<div id="gearbox">
  <div class="mrow"><span>${t('langT')}</span><span class="seg">${['no','pl','en'].map(l=>`<button class="${l===lang?'on':''}" data-click="setLang" data-l="${l}">${l.toUpperCase()}</button>`).join('')}</span></div>
  <div class="mrow"><span>${t('themeT')}</span><span class="seg"><button class="${dark?'':'on'}" data-click="setTheme" data-th="light">☀️ ${t('thLight')}</button><button class="${dark?'on':''}" data-click="setTheme" data-th="dark">🌙 ${t('thDark')}</button></span></div>
  <div class="mrow"><span>${t('pDef')}</span><span class="stp"><button class="b" data-click="setDef" data-n="${S.servings_default-1}" aria-label="−">−</button><b>${S.servings_default}</b><button class="b" data-click="setDef" data-n="${S.servings_default+1}" aria-label="+">+</button></span></div>
  <div class="msec"><b>👎 ${t('dislikesT')}</b> <span class="desc">${t('dislikesSub')}</span>
  ${dl.length?dl.map(d=>`<div class="mrow"><span>${esc(d.name)}${d.reason?` <i>– ${esc(d.reason)}</i>`:''}</span><button class="b" aria-label="${esc(t('restore'))}" data-click="undislike" data-id="${d.id}">✕</button></div>`).join(''):`<div class="desc">${t('dislikesNone')}</div>`}</div></div>
  ${S.week?`<button class="act danger" data-click="delWeek" data-id="${S.week.id}">${t('delWeek')} · ${t('wk')}${isoWk(S.week.start)}</button>`:''}`}
function isoWk(ds){const x=new Date(ds+'T12:00:00');x.setDate(x.getDate()+2);const d=new Date(Date.UTC(x.getFullYear(),x.getMonth(),x.getDate()));const n=d.getUTCDay()||7;d.setUTCDate(d.getUTCDate()+4-n);const y=new Date(Date.UTC(d.getUTCFullYear(),0,1));return Math.ceil(((d-y)/864e5+1)/7)}
/* --- nagłówek: jedna linia. Na zakładkach tygodnia i zakupów tydzień ze strzałkami ‹ ›, na pozostałych nazwa zakładki. */
function weekNb(d){const ws=[...((S&&S.weeks)||[])].sort((a,b)=>a.start<b.start?-1:1),i=S&&S.week?ws.findIndex(w=>w.id===S.week.id):-1;return i<0?null:ws[i+d]||null}
function weekStep(d){const w=weekNb(d);if(w)goWeek(w.id===S.current_id?null:w.id,true)}
function headRender(){
  const w=S&&S.week,wk=(tab==='plan'||tab==='shop')&&w;let h;
  if(wk){const tag=w.id!==S.current_id?(w.start>S.today?t('upcoming'):t('archBan')).replace(':',''):'';
    h=`<b>${t('week')} ${isoWk(w.start)} · ${dm(w.start)}–${dm(w.end)}</b>${tag?`<small>${tag}</small>`:''}`}
  else h=`<b>${tab==='fridge'?t('tabW'):tab==='book'?t('tabB'):'Ukesmeny'}</b>`;
  const r=$('#range');if(r._h!==h){r._h=h;r.innerHTML=h}
  [['#wkPrev',-1,'prevWk'],['#wkNext',1,'nextWkA']].forEach(([q,d,k])=>{const b=$(q);b.hidden=!wk;b.disabled=!weekNb(d);b.setAttribute('aria-label',t(k))});
  $('#gear').setAttribute('aria-label',t('menuA'))}
/* --- dolny pasek zakładek; przy zakupach licznik pozycji, które zostały do kupienia */
const TABS=[['plan','tabWk'],['shop','tabS'],['fridge','tabW'],['book','tabB']];
function shopLeft(){let n=0;for(const g of Object.values((S&&S.shopping)||{}))for(const i of g)if(!i.checked)n++;return n}
function navRender(){
  TABS.forEach(([k,l])=>{const b=$('#n_'+k);b.querySelector('span').textContent=t(l);b.classList.toggle('on',tab===k);
    if(tab===k)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  const n=shopLeft(),c=$('#n_cnt');c.textContent=n||'';c.hidden=!n;c.classList.toggle('alert',!!(S&&S.shop_alert>0))}
let forceRender=false;
function render(){
  headRender();navRender();
  // Listę przebudowujemy tylko wtedy, gdy jej treść się zmieniła (patrz paint). Odświeżenie w tle, które nic nie zmienia,
  // nie podmienia więc elementu pod palcem (dotknięcie trwające w chwili podmiany przepadało). forceRender wymusza
  // przebudowę, gdy trzeba cofnąć coś, co zmieniło się tylko na ekranie (zaznaczone pole po nieudanym zapisie).
  paint($('#main'),tab==='plan'?plan():tab==='shop'?shop():tab==='book'?book():fridge(),forceRender);forceRender=false;
  renderSheet();
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
/* --- tydzień: jeden wiersz na dzień (data, nazwa, kółko „zrobione”). Data jest uchwytem do przeciągania, dotknięcie
   nazwy otwiera przepis, a rzadkie akcje są w arkuszu pod ⋯. Dzisiejszy dzień jest rozwinięty. */
function mealState(m){   // dopisek pod nazwą, tylko gdy z daniem coś się dzieje
  if(m.loading||(m.alts&&m.alts.length===0))return '⏳ '+t('bSwap');
  if(m.alts&&m.alts.length)return t('readyT');
  if(m.draft&&m.filling)return '⏳ '+t('recWait');
  if(m.draft&&(m.draft_error||S.week.confirmed))return '⚠ '+t('recNone');
  if(m.overdue&&m.status==='planned')return '⚠ '+t('overdueS');
  return ''}
function mealCard(m){const v=mv(m),id=m.id,isT=m.date===S.today,done=m.status==='done';
  const d=`<span class="d handle"><small>${esc(isT?t('today'):t('daysS')[m.day])}</small><b>${m.date.slice(8)}</b></span>`;
  const more=`<button class="mb" data-click="sheetMeal" data-id="${id}" aria-label="${esc(t('actions'))}">⋯</button>`;
  if(m.status==='removed')return `<div class="meal off" data-id="${id}"><div class="dr">${d}
   <button class="nmb" data-click="sheetMeal" data-id="${id}"><span class="name">${t('dayOffS')}</span><span class="desc"><s>${esc(v.name)}</s></span></button>
   <button class="mb" data-click="st" data-id="${id}" data-s="planned" aria-label="${esc(t('restore'))}" title="${esc(t('restore'))}">↺</button></div></div>`;
  const sub=[mealState(m),...(isT?[m.time_min?m.time_min+' min':'',m.servings_eff+' '+t('por'),m.is_fish?t('fish'):'']:[]),
    m.status==='skipped'?t('tSkip'):'',m.owned?t('tCarry'):''].filter(Boolean).map(esc).join(' · ');
  const ck=`<button class="ck ${done?'on':''}" data-click="toggleDone" data-id="${id}" aria-pressed="${done}" aria-label="${esc(t('markDoneA'))}"></button>`;
  return `<div class="meal ${done?'done':''} ${m.overdue&&m.status==='planned'?'late':''}" data-id="${id}"><div class="dr">${d}
   <button class="nmb" data-click="openMeal" data-id="${id}"><span class="name">${esc(v.name)}</span>${sub?`<span class="desc">${sub}</span>`:''}</button>
   ${isT?'':more+ck}</div>
   ${isT?`<div class="tr"><button class="b p" data-click="openMeal" data-id="${id}">📖 ${t('recipe')}</button>
    <button class="b dn ${done?'on':''}" data-click="toggleDone" data-id="${id}" aria-pressed="${done}">${t('markDone')}</button><span class="sp"></span>${more}</div>`:''}</div>`}
function plan(){
  if(!S.week)return `<div class="card">${t('noplan')}<div class="row"><button class="b p" data-click="goTab" data-t="fridge">${t('goPlanner')}</button></div></div>`;
  let h='';
  if(S.week.id!==S.current_id)h+=`<div class="strip"><span>${(S.week.start>S.today?t('upcoming'):t('archBan')).replace(':','')}</span><button class="b" data-click="goWeek" data-id="">${t('backCur')}</button></div>`;
  if(S.carry.length)h+=`<div class="warn">${t('waiting')} ${S.carry.map(esc).join(', ')}</div>`;
  if(S.week.confirmed===false)h+=`<div class="warn" style="background:var(--info);border-color:var(--infobd)"><b>${t('confTitle')}</b><div class="desc" style="margin-top:4px">${t('confTxt')}</div><div class="row"><button class="b p" data-click="confirmPlan">${t('confirmBtn')}</button></div></div>`;
  h+='<div class="week">'+S.meals.map(m=>`<div class="slot ${m.date===S.today?'today':''} ${m.date<S.today?'past':''} ${m.status==='removed'?'offday':''}" data-day="${m.day}">${mealCard(m)}</div>`).join('')+'</div>';
  return h}
function openMeal(id){const m=gm(id);if(!m)return;
  openSheet({kind:m.status==='removed'||m.overdue||m.loading||m.alts!=null?'meal':'rec',id})}   // gdy danie czeka na decyzję, od razu arkusz akcji
// Podgląd przepisu (dotknięcie wiersza). Szkic bez przepisu pokazuje same nazwy składników i, gdy nikt go nie pisze, przycisk „Napisz przepis”.
function recSheet(m){const v=mv(m),id=m.id;let body;
  if(m.draft){
    body=m.filling?`<div class="note">⏳ ${t('recWait')}</div>`
     :(m.draft_error||S.week.confirmed)?`<div class="note">${t('recNone')}</div><div class="row"><button class="b p" data-click="retryRec" data-id="${id}">✍ ${t('recWrite')}</button></div>`:'';
    body+=`<h3>${t('sectIng')}</h3>${ingList(m.ingredient_names||[])}`;
  }else body=`<h3>${t('sectIng')}</h3><ul class="ings">${m.ingredients.map((i,k)=>`<li>${esc(m.qv[k]??'')} ${esc(i.unit)} ${esc(v.ing[k]||i.name)}</li>`).join('')}</ul>
   <h3>${t('sectStp')}</h3><ol class="steps">${v.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol>
   ${okUrl(m.source)?`<a class="lnk" href="${esc(m.source)}" target="_blank" rel="noopener">${t('src')} ↗</a>`:''}`;
  return `${sheetHead(esc(v.name))}<div class="desc">${[v.description,m.time_min?m.time_min+' min':'',m.servings_eff+' '+t('por'),m.is_fish?t('fish'):''].filter(Boolean).map(esc).join(' · ')}</div>
   ${body}<div class="row"><button class="b" data-click="sheetMeal" data-id="${id}">⋯ ${t('actions')}</button></div>`}
// Arkusz akcji dania: zamiana (podpowiedzi, własne życzenie, propozycje), przeniesienie, porcje, przepisy, 👎, usunięcie.
function mealSheet(m){const v=mv(m),id=m.id,D=t('days');
  const head=sheetHead(esc(v.name))+`<div class="desc">${esc(D[m.day])} ${dm(m.date)}</div>`;
  const move=`<div class="lbl">${t('moveBtn')}</div><div class="chips">${t('daysS').map((x,k)=>k===m.day?'':`<button class="chip" data-click="mv2" data-id="${id}" data-d="${k}" aria-label="${esc(D[k])}">${esc(x)}</button>`).join('')}</div>`;
  if(m.status==='removed')return `${sheetHead(t('dayOffS'))}<div class="desc">${esc(D[m.day])} ${dm(m.date)} · <s>${esc(v.name)}</s></div>
   <button class="act" data-click="st" data-id="${id}" data-s="planned">↺ ${t('restore')}</button>
   <button class="act" data-click="restoreSwap" data-id="${id}">🔄 ${t('otherDish')}</button>${move}`;
  const dis=m.disliked?`<button class="act" data-click="dislikeOff" data-id="${id}" aria-label="dislike" aria-pressed="true">👎 ${t('dislikeT')} ✓ <span class="desc">${t('undo')}</span></button>`
   :sheet.why?`<div class="alt"><b>👎 ${t('dislikeT')}</b><div class="desc">${t('dislikeQ')}</div>
     <div class="inrow"><input id="why${id}" placeholder="${esc(t('dislikePh'))}" data-enter="dislikeSave" data-id="${id}"><button class="b p" data-click="dislikeSave" data-id="${id}">${t('save')}</button></div>
     <div class="row"><button class="b" data-click="dislikeCancel">${t('cancel')}</button></div></div>`
   :`<button class="act" data-click="dislikeAsk" aria-label="dislike" aria-pressed="false">👎 ${t('dislikeT')}</button>`;
  // zaległe danie (dzień minął, a nie jest odhaczone): decyzja na górze arkusza
  const late=m.overdue?`<div class="note"><b>${t('overdueQ')}</b><div class="row"><button class="b p" data-click="st" data-id="${id}" data-s="done">${t('markDone')}</button>
    <button class="b" data-click="carry" data-id="${id}">${t('carry')}</button><button class="b" data-click="st" data-id="${id}" data-s="skipped">${t('skip')}</button></div></div>`:'';
  return `${head}${late}<button class="act" data-click="openRec" data-id="${id}">📖 ${t('recipe')}</button>
   ${m.status==='planned'||m.alts!=null||m.loading?`<div id="alt${id}">${altsHtml(m)}</div>`:''}${move}
   <div class="mrow"><span>👥 ${t('porT')}</span><span class="stp"><button class="b" data-click="srv" data-id="${id}" data-n="${m.servings_eff-1}" aria-label="−">−</button><b>${m.servings_eff}</b><button class="b" data-click="srv" data-id="${id}" data-n="${m.servings_eff+1}" aria-label="+">+</button>${m.servings?`<button class="b" data-click="srv" data-id="${id}" data-n="" aria-label="${esc(t('restore'))}">↺</button>`:''}</span></div>
   <button class="act" data-click="fav" data-id="${id}" aria-label="favorite" aria-pressed="${!!m.fav}">⭐ ${m.fav?t('favOn')+' ✓':t('favAdd')}</button>
   ${dis}
   ${m.status==='planned'?`<button class="act danger" data-click="removeDay" data-id="${id}">🗑 ${t('removeDayL')}</button>`:''}`}
const SWAPS=['swRice','swLight','swQuick'];
function altsHtml(m){const id=m.id;
  if(m.loading||(m.alts&&m.alts.length===0))return `<div class="altwrap" id="aw${id}"><div class="finding"><div class="spinner"></div><div><div class="ft">🔄 ${t('bSwap')}</div><div class="fs">${t('findSub')}</div></div></div><div class="row"><button class="b" data-click="closeAlt" data-id="${id}">${t('cancel')}</button></div><div class="skel"></div><div class="skel"></div></div>`;
  const ask=`<div class="inrow"><input id="hint${id}" placeholder="${esc(t('askPh'))}" value="${esc(m.hint||'')}" data-enter="findAlts" data-id="${id}"><button class="b p" data-click="findAlts" data-id="${id}">${t('find')}</button></div>`;
  // jeszcze nic nie szukano: gotowe podpowiedzi jednym dotknięciem albo własne życzenie
  if(!m.alts)return `<div class="swap"><div class="lbl">🔄 ${t('swapBtn')}</div><div class="chips">${SWAPS.map(k=>`<button class="chip" data-click="swapHint" data-id="${id}" data-h="${esc(t(k))}">${t(k)}</button>`).join('')}<button class="chip" data-click="swapHint" data-id="${id}" data-h="">✨ ${t('surprise')}</button></div>${ask}</div>`;
  return `<div class="altwrap ${m.justReady?'ready':''}" id="aw${id}"><div class="${m.justReady?'readyb':'lbl'}">${t('readyT')}${m.justReady?' ↓':''}</div>`+m.alts.map((o,i)=>{const k=id+':'+i,op=!!openAIng[k];return `<div class="alt"><b>${esc(o.name)}</b><div class="desc">${esc(o.description)}</div>
  ${(o.ingredients||[]).length?`<button class="lnk" data-click="toggleAIng" data-k="${k}">${op?t('hideIng')+' ▴':t('showIng')+' ▾'}</button>${op?ingList(o.ingredients):''}`:''}
  <div class="row"><button class="b p" ${m.choosing!=null?'disabled':''} data-click="choose" data-id="${id}" data-i="${i}">${m.choosing===i?'⏳':t('choose')}</button></div></div>`}).join('')+
  `<div class="alt">${ask}<div class="row"><button class="b" data-click="closeAlt" data-id="${id}">${t('cancel')}</button></div></div></div>`}
// Propozycje gotowe: gdy arkusz dania jest otwarty, podświetlamy je w nim; gdy nie, komunikat z przyciskiem „Pokaż”.
function attention(id){const m=gm(id);if(!m)return;m.justReady=true;render();
  const shown=sheet&&sheet.kind==='meal'&&sheet.id===id;
  const el=document.getElementById('aw'+id);if(el)el.scrollIntoView({behavior:'smooth',block:'start'});
  toast(t('readyT'),shown?null:{label:t('show'),fn:()=>openSheet({kind:'meal',id})});try{navigator.vibrate&&navigator.vibrate(60)}catch(e){}
  setTimeout(()=>{const mm=gm(id);if(mm)mm.justReady=false;render()},4500)}
const usesOpen=new Set();
function togUses(k){usesOpen.has(k)?usesOpen.delete(k):usesOpen.add(k);render()}
function useLine(u,withQty){const m=(S.meals||[]).find(x=>x.id===u.meal);const q=withQty&&u.qty?` – ${esc(u.qty)} ${esc(u.unit)}`:'';
  return `${esc(t('daysS')[u.day])} · ${esc(m?rv(m).name:'')}${q}`}
// W ilu daniach jest produkt. Jedno danie: sama linia. Kilka: linia z dniami, a szczegóły z ilościami rozwija przycisk ▾ na końcu wiersza.
function usesHtml(i,k){const u=i.uses||[];if(!u.length)return '';
  if(u.length===1)return `<div class="use">${useLine(u[0])}</div>`;
  return `<div class="use">${t('usedIn').replace('{n}',u.length)}: ${u.map(x=>esc(t('daysS')[x.day])).join(', ')}</div>`+(usesOpen.has(k)?u.map(x=>`<div class="use">${useLine(x,true)}</div>`).join(''):'')}
function usesBtn(i,k){return (i.uses||[]).length>1?`<button type="button" class="mb" data-click="togUses" data-k="${esc(k)}" aria-label="${esc(t('usesA'))}" aria-expanded="${usesOpen.has(k)}">${usesOpen.has(k)?'▴':'▾'}</button>`:''}
function headsTxt(i){if(!i.heads)return '';const w=t('heads');return ` <span class="use" style="text-decoration:none">(≈ ${i.heads} ${i.heads===1?w[0]:w[1]})</span>`}
function shopRow(i){return `<label class="${i.checked?'c':''}"><input type="checkbox" ${i.checked?'checked':''} data-change="chk" data-k="${esc(i.key)}"><div class="li"><span>${i.topup?'<b>+ </b>':''}${esc(i.qty)} ${esc(i.unit)} ${esc(i.extra_id?i.name:nm(i.name))}</span>${headsTxt(i)}${i.topup?` <span class="tag" style="background:var(--badbg);color:var(--bad)">${t('buyMore')}</span>`:''}${usesHtml(i,i.key)}</div>${usesBtn(i,i.key)}${i.extra_id?`<button type="button" class="mb" data-click="delX" data-id="${i.extra_id}" aria-label="${esc(t('del'))}">✕</button>`:''}</label>`}
/* --- zakupy: pasek postępu, w działach tylko to, co zostało do kupienia (z licznikiem), odhaczone zjeżdżają do zwiniętej
   sekcji „Kupione” na dole, pole dopisywania przy dolnej krawędzi. */
function shop(){
  if(!S.week)return '';
  const g=S.shopping||{},all=Object.values(g).flat(),done=all.filter(i=>i.checked),of=(a,b)=>t('ofN').replace('{a}',a).replace('{b}',b);
  let h='<div class="shop">';
  if(all.length)h+=`<div class="shead"><b>${of(done.length,all.length)}</b><span class="desc">${t('leftN').replace('{n}',all.length-done.length)}</span><span class="sp"></span><button class="b" data-click="copyList">⧉ ${t('copyS')}</button></div>
   <div class="pbar" role="progressbar" aria-valuemin="0" aria-valuemax="${all.length}" aria-valuenow="${done.length}"><i style="width:${Math.round(100*done.length/all.length)}%"></i></div>`;
  if(S.pending)h+=`<div class="warn">${t('shopWait')}</div>`;
  if(!all.length&&!S.pending)h+=`<div class="card">${t('empty')}</div>`;
  if(all.length&&done.length===all.length)h+=`<div class="card">✓ ${t('allBought')}</div>`;
  for(const [a,items] of Object.entries(g)){const todo=items.filter(i=>!i.checked);if(!todo.length)continue;
    h+=`<h3><span>${esc(t(a))}</span><span class="cnt">${of(items.length-todo.length,items.length)}</span></h3>`+todo.map(shopRow).join('')}
  if((S.gone||[]).length)h+=`<h3 style="color:var(--orange)">${t('goneT')}</h3>`+S.gone.map(g=>`<div class="mrow"><span>✓ ${esc(g.label)}</span><button class="b" data-click="dismissG" data-k="${esc(g.key)}">${t('dismiss')}</button></div>`).join('');
  if(done.length)h+=`<button type="button" class="bhead" data-click="foldSec" data-k="bought" aria-expanded="${!!sec.bought}"><span>${t('bought')} (${done.length})</span><span>${sec.bought?'▾':'▸'}</span></button>`+(sec.bought?`<div class="bought">${done.map(shopRow).join('')}</div>`:'');
  if(S.have.length)h+=`<h3>${t('have')}</h3>`+S.have.map(i=>`<div class="haverow"><div class="li">${esc(i.qty)} ${esc(i.unit)} ${esc(nm(i.name))}${usesHtml(i,'have:'+i.key)}</div>${usesBtn(i,'have:'+i.key)}</div>`).join('');
  return h+`<div class="addbar"><input id="xn" placeholder="${esc(t('addPh'))}" data-enter="addX"><button class="b p" data-click="addX" aria-label="${esc(t('add'))}">+</button></div></div>`}
/* --- zakładka Przepisy: książka z wyszukiwaniem, podgląd przepisu, „Wstaw na dzień”, własny przepis */
let bookQ='';
function bookPicked(){return new Map(S.cravings.filter(c=>!c.used&&c.recipe_id).map(c=>[c.recipe_id,c.id]))}
function bookList(){const rs=S.recipes||[],q=bookQ.trim().toLowerCase(),picked=bookPicked();
  if(!rs.length)return `<div class="card">${t('bookEmpty')}</div>`;
  const list=rs.filter(r=>{if(!q)return true;const v=rv(r);return [v.name,v.description,r.name,...v.ing,...r.ingredients.map(i=>i.name)].join(' ').toLowerCase().includes(q)});
  if(!list.length)return `<div class="card">${t('bookNone')}</div>`;
  return list.map(r=>{const v=rv(r),on=picked.has(r.id);return `<div class="brow" data-rid="${r.id}"><button class="nmb" data-click="openBook" data-id="${r.id}"><span class="name">${esc(v.name)}</span><span class="desc">${esc([r.time_min?r.time_min+' min':'',v.description].filter(Boolean).join(' · '))}</span></button>
   <button class="chip ${on?'on':''}" data-click="togglePick" data-id="${r.id}" aria-pressed="${on}">${on?'✓ '+t('inPlan'):'＋ '+t('toPlan')}</button></div>`}).join('')}
function book(){return `<div class="book"><div class="inrow"><input id="bq" placeholder="${esc(t('bookSearch'))}" value="${esc(bookQ)}" data-input="bookQ" autocomplete="off"><button class="b" data-click="toggleCust">➕ ${t('custBtn')}</button></div>
  ${custOpen?custPanel():''}<div class="desc bhint">${t('bookHint')}</div><div id="blist">${bookList()}</div></div>`}
// Podgląd przepisu z książki. „Wstaw na dzień” ma dwa kroki: wybór dnia pokazuje, jakie danie zostanie zastąpione, dopiero „Wstaw tutaj” zapisuje.
function bookSheet(r){const v=rv(r),on=bookPicked().has(r.id),D=t('days');let use='';
  if(S.week){const k=sheet.day,m=k!=null?S.meals.find(x=>x.day===k):null;
    use=`<div class="lbl">${t('useT')} · ${t('wk')}${isoWk(S.week.start)}</div><div class="chips">${t('daysS').map((x,i)=>`<button class="chip ${i===k?'on':''}" data-click="useDay" data-d="${i}" aria-label="${esc(D[i])}" aria-pressed="${i===k}">${esc(x)}</button>`).join('')}</div>`
     +(m?`<div class="alt"><b>${esc(D[k])} ${dm(m.date)}</b><div class="desc">${m.status==='removed'?t('dayOffS'):esc(t('useNow').replace('{x}',mv(m).name))}</div>
      <div class="row"><button class="b p" data-click="useRec" data-id="${r.id}" data-d="${k}">${t('useGo')}</button></div></div>`:'')}
  return `${sheetHead(esc(v.name))}<div class="desc">${esc([v.description,r.time_min?r.time_min+' min':''].filter(Boolean).join(' · '))}</div>
   ${use}<button class="act" data-click="togglePick" data-id="${r.id}" aria-pressed="${on}">${on?'✓ '+t('inPlan'):'＋ '+t('toPlan')}</button>
   <h3>${t('sectIng')}</h3><ul class="ings">${r.ingredients.map((i,k)=>`<li>${esc(i.qty??'')} ${esc(i.unit)} ${esc(v.ing[k]||i.name)}</li>`).join('')}</ul>
   <h3>${t('sectStp')}</h3><ol class="steps">${v.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol>
   ${okUrl(r.source)?`<a class="lnk" href="${esc(r.source)}" target="_blank" rel="noopener">${t('src')} ↗</a>`:''}
   <button class="act danger" data-click="delRecAsk" data-id="${r.id}">🗑 ${t('delRecL')}</button>`}
function delRecAsk(id){const r=(S.recipes||[]).find(x=>x.id===id);if(!r)return;
  sheet=null;openSheet({kind:'confirm',title:rv(r).name,text:t('delRecQ'),yes:t('del'),fn:()=>delRec(id)})}
function rv(r){const x=lang!=='no'&&r.tr&&r.tr[lang];return x?{name:x.name,description:x.description,ing:x.ingredients,steps:x.steps}:{name:r.name,description:r.description,ing:r.ingredients.map(i=>i.name),steps:r.steps}}
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
function goTab(k){tab=k;render();window.scrollTo(0,0)}
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
   <ul style="list-style:none;padding:0">${S.pantry.map(p=>`<li class="mrow"><span>${esc(p.name)}</span><button type="button" class="mb" data-click="delP" data-id="${p.id}" aria-label="${esc(t('del'))}">✕</button></li>`).join('')}</ul></div>`:''}</div>
  <div class="card">${secHead('crav','😋',t('cTitle'),free.filter(c=>!c.recipe_id).length+picked.size,[...free.filter(c=>!c.recipe_id).map(c=>c.text),...(S.recipes||[]).filter(r=>picked.has(r.id)).map(r=>rv(r).name)].join(', '))}${sec.crav?`<div class="secbody"><div class="desc" style="font-size:12px;margin-top:2px">${t('linkHint')}</div>
   <div class="row"><input id="cn" placeholder="${esc(t('cPh'))}" data-enter="addC" style="flex:1"><button class="b p" data-click="addC">${t('add')}</button></div>
   <ul style="list-style:none;padding:0">${free.filter(c=>!c.recipe_id).map(c=>`<li class="mrow"><span>${esc(c.text)}</span><button type="button" class="mb" data-click="delC" data-id="${c.id}" aria-label="${esc(t('del'))}">✕</button></li>`).join('')}</ul></div>`:''}</div>
  <div class="card"><div class="mrow" style="border:0"><span><b>⭐ ${t('book')}</b> <span class="cnt">${(S.recipes||[]).length}</span><div class="desc">${t('bookPickHint')}</div></span><button class="b" data-click="goTab" data-t="book">${t('open')} →</button></div>
   ${(S.recipes||[]).filter(r=>picked.has(r.id)).map(r=>`<div class="mrow"><span>✓ ${esc(rv(r).name)}</span><button type="button" class="mb" data-click="togglePick" data-id="${r.id}" aria-label="${esc(t('del'))}">✕</button></div>`).join('')}</div>
  ${draft?'':`<div class="row"><button class="b p" style="flex:1;padding:14px;font-size:16px" ${jobRunning?'disabled':''} data-click="gen">${t('goBtn')}</button></div>`}`;
  return h}
// Usunięcie całego tygodnia: jedyna akcja z potwierdzeniem (nie da się jej cofnąć), ale we własnym arkuszu, nie w oknie systemowym.
function delWeek(wid){const w=(S.weeks||[]).find(x=>x.id===wid);
  sheet=null;openSheet({kind:'confirm',title:w?`${t('week')} ${isoWk(w.start)} · ${dm(w.start)}`:t('delWeek'),text:t('delWeekQ'),yes:t('delWeekYes'),fn:()=>doDelWeek(wid)})}
async function doDelWeek(wid){wizDraft=null;viewWeek=null;
  const r=await api('/api/week/'+wid,'DELETE');if(r){adopt(r);render();ensureTr()}}
async function confirmWeek(wid){wizDraft=null;const r=await api('/api/week/confirm','POST',{week:wid},t('jFill'));
  if(r){const jid=r.job;viewWeek=wid===r.current_id?null:wid;set(r);goTab('plan');if(jid){jobId=jid;clearTimeout(jobTimer);pollJob()}}}
async function takeRec(rid,on){const ex=S.cravings.find(c=>!c.used&&c.recipe_id===rid);
  if(on&&!ex)set(await api('/api/cravings','POST',{recipe_id:rid}));
  else if(!on&&ex)set(await api('/api/cravings/'+ex.id,'DELETE'))}
async function goWeek(id,keepTab){viewWeek=id;if(!keepTab)tab='plan';await load()}
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
// „Zrobione” zmienia się na ekranie od razu; gdy zapis się nie uda, wraca do poprzedniego stanu (komunikat pokazuje api()).
async function toggleDone(id){const m=gm(id);if(!m)return;const was=m.status,s=was==='done'?'planned':'done';m.status=s;render();
  const r=await api(`/api/meal/${id}/status`,'POST',{status:s});
  if(r)set(r);else{const mm=gm(id);if(mm&&mm.status===s){mm.status=was;forceRender=true;render()}}}
// Usunięcie obiadu z dnia bez pytania „czy na pewno”: status removed da się przywrócić, więc wystarczy „Cofnij” w komunikacie.
async function removeDay(id){closeSheet();const r=await api(`/api/meal/${id}/status`,'POST',{status:'removed'});if(!r)return;set(r);
  toast(t('removedT'),{label:t('undo'),fn:()=>st(id,'planned')})}
async function dislikeSave(id){const why=(($('#why'+id)||{}).value||'').trim();
  const r=await api(`/api/meal/${id}/dislike`,'POST',{reason:why});if(!r)return;
  if(sheet)sheet.why=false;set(r);toast('👎 '+t('dislikeDone'));$('#panel').scrollTop=0}
async function dislikeOff(id){const r=await api(`/api/meal/${id}/dislike`,'POST',{reason:''});if(r){set(r);toast(t('dislikeOff'))}}
async function undislike(did){set(await api(`/api/dislikes/${did}`+(viewWeek?`?week=${viewWeek}`:''),'DELETE'))}
async function fav(id){const r=await api(`/api/meal/${id}/favorite`);if(r){const m=r.meals.find(x=>x.id===id);set(r);if(m&&m.fav)toast('⭐ '+t('favOn'))}}
async function carry(id){set(await api(`/api/meal/${id}/carry`))}
function toggleAIng(k){openAIng[k]=!openAIng[k];render()}
async function confirmPlan(){const r=await api('/api/week/confirm','POST',W({}),t('jFill'));if(r){const jid=r.job;set(r);if(jid){jobId=jid;clearTimeout(jobTimer);pollJob()}}}
async function retryRec(id){set(await api(`/api/meal/${id}/recipe`))}
async function setDef(n){if(n<1||n>12)return;set(await api('/api/settings','POST',{servings:n}))}
async function srv(id,n){if(n!==null&&(n<1||n>12))return;set(await api(`/api/meal/${id}/servings`,'POST',{servings:n}))}
function openAlt(id){const m=gm(id);if(!m)return;m.open=true;m.alts=null;m.loading=false;m.closing=false;openSheet({kind:'meal',id})}
const altReq={};let altSeq=0;   // numer trwającego szukania dla dania; „Anuluj” go kasuje, więc spóźniona odpowiedź nie otwiera propozycji z powrotem
async function clearAlts(id){try{await fetch(`/api/meal/${id}/alts/clear`,{method:'POST'})}catch(e){}}
async function closeAlt(id){const m=gm(id);if(!m)return;
  const running=altReq[id]!=null;delete altReq[id];
  m.open=false;m.alts=null;m.hint='';m.loading=false;m.closing=true;render();
  await clearAlts(id);
  if(running)return;   // serwer jeszcze szuka i na koniec zapisze propozycje: posprząta po nich findAlts, gdy wróci odpowiedź
  const mm=gm(id);if(mm)mm.closing=false}
const gm=id=>S.meals.find(x=>x.id===id);
async function findAlts(id,hintOv){let m=gm(id);if(!m)return;   // hintOv: życzenie z gotowej podpowiedzi ('' = „zaskocz mnie”), bez niego tekst z pola
  const hint=(typeof hintOv==='string'?hintOv:(($('#hint'+id)||{}).value||'')).trim();m.hint=hint;m.loading=true;m.justReady=false;m.alts=null;render();
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
    const d=await r.json();const mm=gm(id);if(mm)mm.choosing=null;set(d);if(sheet&&sheet.kind==='meal'&&sheet.id===id)closeSheet()}catch(e){const mm=gm(id);if(mm)mm.choosing=null;toast(t('err')+e.message);render()}}
async function mv2(id,d){if(d==='')return;set(await api(`/api/meal/${id}/move`,'POST',{day:+d}))}
// Po udanym dopisaniu pole się czyści (o ile nikt nie zdążył wpisać w nie czegoś nowego); po błędzie tekst zostaje do poprawienia.
function added(sel,v,r){const e=$(sel);if(r&&e&&e.value===v)e.value='';return r}
async function addP(){const v=$('#pn').value;if(!v.trim())return;set(added('#pn',v,await api('/api/pantry','POST',{name:v})))}
async function delP(id){set(await api('/api/pantry/'+id,'DELETE'))}
async function addC(){const raw=$('#cn').value,v=raw.trim();if(!v)return;const isU=/^https?:\/\/\S+$/i.test(v);
  const r=added('#cn',raw,await api('/api/cravings','POST',{text:v},isU?t('bImport'):undefined));if(r){set(r);if(isU)toast('⭐ '+t('favOn'))}}
async function delC(id){set(await api('/api/cravings/'+id,'DELETE'))}
async function delRec(id){set(await api('/api/recipes/'+id,'DELETE'))}
async function useRec(id,d){const rc=(S.recipes||[]).find(x=>x.id===id);closeSheet();
  const r=await api(`/api/recipes/${id}/use`,'POST',W({day:d}));if(r){set(r);tab='plan';render();window.scrollTo(0,0);toast('✓ '+t('usedT')+(rc?rv(rc).name:''))}}
async function addX(){const v=$('#xn').value;if(!v.trim())return;set(added('#xn',v,await api('/api/shop/extra','POST',W({name:v}))))}
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
  try{await navigator.clipboard.writeText(x);toast(t('copied'))}
  catch(e){openSheet({kind:'text',title:t('copy'),text:x})}}   // schowek niedostępny (np. bez HTTPS): lista do ręcznego skopiowania
/* --- przeciąganie dania między dniami. Uchwytem jest data w wierszu; karta jedzie za palcem w obu osiach (na szerokim
   ekranie dni leżą obok siebie). Dotknięcie daty bez ruchu działa jak dotknięcie nazwy: otwiera przepis. */
let drag=null;
function slotAt(x,y){if(!drag)return null;const c=drag.card;c.style.visibility='hidden';const el=document.elementFromPoint(x,y);c.style.visibility='';
  const sl=el&&el.closest('.slot[data-day]');return sl&&sl!==drag.slot?sl:null}
function dragLoop(){if(!drag)return;
  if(!drag.moved&&Math.hypot(drag.x-drag.x0,drag.y-drag.y0)>6){drag.moved=true;drag.card.classList.add('dragging')}
  if(drag.moved){
    drag.card.style.transform=`translate(${drag.x-drag.x0}px,${(drag.y-drag.y0)+(window.scrollY-drag.s0)}px)`;
    if(drag.y<90)window.scrollBy(0,-10);else if(drag.y>innerHeight-110)window.scrollBy(0,10);
    document.querySelectorAll('.slot.over').forEach(c=>c.classList.remove('over'));
    const sl=slotAt(drag.x,drag.y);if(sl)sl.classList.add('over')}
  requestAnimationFrame(dragLoop)}
document.addEventListener('pointerdown',e=>{const hd=e.target.closest&&e.target.closest('.handle');if(!hd||drag)return;
  e.preventDefault();const card=hd.closest('.meal');
  drag={card,slot:card.closest('.slot'),id:+card.dataset.id,x:e.clientX,y:e.clientY,x0:e.clientX,y0:e.clientY,s0:window.scrollY,moved:false};
  try{hd.setPointerCapture(e.pointerId)}catch(_){}
  requestAnimationFrame(dragLoop)});
document.addEventListener('pointermove',e=>{if(drag){drag.x=e.clientX;drag.y=e.clientY;e.preventDefault()}},{passive:false});
function endDrag(e,cancel){if(!drag)return;const d=drag;
  if(!cancel&&!d.moved&&Math.hypot(e.clientX-d.x0,e.clientY-d.y0)>6){d.moved=true}
  const sl=cancel||!d.moved?null:slotAt(e.clientX,e.clientY);drag=null;
  d.card.classList.remove('dragging');d.card.style.transform='';
  document.querySelectorAll('.slot.over').forEach(c=>c.classList.remove('over'));
  if(sl)mv2(d.id,sl.dataset.day);else if(!cancel&&!d.moved)openMeal(d.id);else render()}
document.addEventListener('pointerup',e=>endDrag(e,false));
document.addEventListener('pointercancel',e=>endDrag(e,true));
function applyTheme(){const s=localStorage.getItem('theme');const d=s?s==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
  if(d)document.documentElement.setAttribute('data-theme','dark');else document.documentElement.removeAttribute('data-theme');
  const mt=document.querySelector('meta[name=theme-color]');if(mt)mt.content=d?'#1f4a31':'#2f7d4f'}
function setTheme(th){localStorage.setItem('theme',th);applyTheme();if(S)render()}
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
/* --- nowa wersja po wdrożeniu. Sam ?v= przy plikach działa dopiero, gdy przeglądarka pobierze świeży index.html,
   a karta potrafi być otwarta tygodniami (i serwer nie zabrania trzymać index.html w pamięci podręcznej).
   Przy starcie, po powrocie do aplikacji i co 10 minut porównujemy więc ?v= z index.html na serwerze z tymi,
   z którymi strona się załadowała. Gdy się różnią, przeładowujemy stronę: raz na daną wersję, nie w trakcie
   pisania ani zapisu. */
const verOf=h=>(h.match(/\/static\/[\w.]+\?v=\w+/g)||[]).sort().join(' ');
const myVer=verOf(document.documentElement.innerHTML);
let verAt=0;
async function checkVersion(){
  if(document.hidden||busyUI()||custOpen||sheet||Date.now()-verAt<60000)return;verAt=Date.now();
  try{const r=await fetch('/',{cache:'no-store'});if(!r.ok)return;const v=verOf(await r.text());
    if(!v||v===myVer||sessionStorage.getItem('reloadedFor')===v)return;
    sessionStorage.setItem('reloadedFor',v);location.reload()}catch(e){}}
checkVersion();setInterval(checkVersion,600000);
document.addEventListener('visibilitychange',checkVersion);
window.addEventListener('focus',checkVersion);
