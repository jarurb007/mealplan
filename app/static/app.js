const $=s=>document.querySelector(s);
/* Ikony: jeden zestaw SVG (siatka 24, cienki kontur, kształty z klasą f mają półprzezroczyste wypełnienie).
   ic('nazwa') zwraca gotowy znacznik; elementy z data-ic w index.html dostają ikonę przy starcie. */
const IC={
 week:'<rect class="f" x="4" y="5.5" width="16" height="14.5"/><path d="M4 10.5h16M8 3.5v4M16 3.5v4"/>',
 shop:'<path class="f" d="M3.5 10h17l-1.7 9.5H5.2z"/><path d="M8 10l3-6M16 10l-3-6M9.5 13v3.5M14.5 13v3.5"/>',
 plan:'<path class="f" d="M11 3.5l1.9 5.1 5.1 1.9-5.1 1.9L11 17.5l-1.9-5.1L4 10.5l5.1-1.9z"/><path d="M18.5 15.5v5M16 18h5"/>',
 book:'<path class="f" d="M12 6.5C10 5 7 4.8 3.5 5.5V18c3.5-.7 6.5-.5 8.5 1 2-1.5 5-1.7 8.5-1V5.5C17 4.8 14 5 12 6.5z"/><path d="M12 6.5V19"/>',
 tasks:'<path d="M3.5 6.5l1.7 1.7 3-3.2M12 6.5h8.5M3.5 13l1.7 1.7 3-3.2M12 13h8.5M4.5 19h3M12 19h8.5"/>',
 done:'<circle class="f" cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.8 2.8 5.4-5.8"/>',
 swap:'<path d="M4 8.5h13.5M14 5l3.5 3.5L14 12M20 15.500H6.500M10 12l-3.5 3.500L10 19"/>',
 move:'<rect class="f" x="13" y="5" width="7.5" height="14"/><path d="M3 12h11M10.5 8l4 4-4 4"/>',
 del:'<path class="f" d="M6.5 8h11l-.9 12H7.400z"/><path d="M4.5 8h15M9.5 8V4.5h5V8M10.3 11.500v5M13.7 11.500v5"/>',
 fav:'<path class="f" d="M12 3.800l2.5 5.2 5.7.8-4.1 4 1 5.700L12 16.800l-5.1 2.7 1-5.7-4.1-4 5.7-.8z"/>',
 bad:'<path class="f" d="M8.5 4.5h7.700a2 2 0 0 1 2 1.600l1 5.500a2 2 0 0 1-2 2.400H14l.6 3.200a1.8 1.8 0 0 1-3.3 1.200L8.5 13.500z"/><rect class="f" x="4" y="4.5" width="4.5" height="9"/>',
 chl:'<path d="M14.5 6l-6 6 6 6"/>',chr:'<path d="M9.5 6l6 6-6 6"/>',chd:'<path d="M6.5 9.5l5.5 5.5 5.5-5.5"/>',chu:'<path d="M6.5 14.500l5.5-5.5 5.5 5.5"/>',
 more:'<circle class="dot" cx="5.5" cy="12" r="1.5"/><circle class="dot" cx="12" cy="12" r="1.5"/><circle class="dot" cx="18.5" cy="12" r="1.5"/>',
 x:'<path d="M6 6l12 12M18 6L6 18"/>',plus:'<path d="M12 5v14M5 12h14"/>',
 pot:'<path class="f" d="M5 10h14v6.500a2.5 2.5 0 0 1-2.5 2.500h-9A2.5 2.5 0 0 1 5 16.500z"/><path d="M2.5 12.500H5M19 12.500h2.500M9.5 4v3M14.5 4v3"/>',
 copy:'<rect class="f" x="8.5" y="8.5" width="11" height="11"/><path d="M5 15V5h10"/>',
 ing:'<path class="f" d="M6 4h12v16.500l-2-1.3-2 1.3-2-1.3-2 1.3-2-1.3-2 1.300z"/><path d="M9 9h6M9 12.500h6"/>',
 sun:'<circle class="f" cx="12" cy="12" r="3.8"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.600l1.4 1.400M17 17l1.4 1.400M18.4 5.600L17 7M7 17l-1.4 1.4"/>',
 moon:'<path class="f" d="M19.5 14.500A8 8 0 0 1 9.5 4.500a8 8 0 1 0 10 10z"/>',
 warn:'<path class="f" d="M12 4l9 15.500H3z"/><path d="M12 10v4.500M12 16.800v.4"/>',
 wait:'<path class="f" d="M7 4h10v3.500l-3.5 4.5 3.5 4.500V20H7v-3.500l3.5-4.500L7 7.500z"/><path d="M5.5 4h13M5.5 20h13"/>',
 undo:'<path d="M5 9.500h9a5 5 0 0 1 0 10H8M8.5 6L5 9.5 8.5 13"/>',
 ppl:'<circle class="f" cx="9" cy="8.5" r="3.2"/><path class="f" d="M3 19.500c0-3.3 2.7-5.5 6-5.500s6 2.2 6 5.500z"/><path d="M15.5 5.600a3.2 3.2 0 0 1 0 5.800M17.5 14.500c2 .7 3.5 2.5 3.5 5"/>',
 cam:'<path class="f" d="M3.5 8h3.500l1.5-2.500h7L17 8h3.500v11h-17z"/><circle cx="12" cy="13.2" r="3.3"/>',
 img:'<rect class="f" x="3.5" y="5" width="17" height="14"/><path d="M3.5 16l4.5-4.5 4 4 2.5-2.5 6 5.5"/><circle class="dot" cx="15.5" cy="9.3" r="1.3"/>',
 pen:'<path class="f" d="M5 19l1-4.500L16.5 4l3.5 3.500L9.5 18z"/><path d="M14.5 6l3.5 3.5"/>',
 snow:'<path d="M12 3v18M4.2 7.500l15.6 9M19.8 7.500l-15.6 9M9.5 4.500L12 7l2.5-2.500M9.5 19.500L12 17l2.5 2.5"/>',
 heart:'<path class="f" d="M12 19.500C5 14.5 3.5 11.5 3.5 9a4.2 4.2 0 0 1 8.5-1 4.2 4.2 0 0 1 8.5 1c0 2.5-1.5 5.5-8.5 10.500z"/>',
 globe:'<circle class="f" cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.500c-5 5-5 12 0 17M12 3.500c5 5 5 12 0 17"/>'
};
const ic=n=>`<svg class="ic" data-i="${n}" viewBox="0 0 24 24" aria-hidden="true">${IC[n]}</svg>`;
let S=null,sheet=null,cook=null,tab='plan',viewWeek=null,openAIng={},pollT=null,
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
  if(msg)bb.textContent=msg;bb.style.display=msg?'block':'none'}
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
function secHead(k,icon,title,cnt,sub,extra){return `<div class="sechead" data-click="foldSec" data-k="${k}"><b>${icon} ${title}</b>${cnt?`<span class="cnt">${cnt}</span>`:''}<span class="sub">${sec[k]?'':esc(sub||'')}</span>${extra||''}<span class="chev">${ic(sec[k]?'chd':'chr')}</span></div>`}
function toggleCust(){custOpen=!custOpen;render()}
function custPanel(){return `<div class="alt" style="margin-top:8px"><b>${t('custTitle')}</b><div class="desc">${t('custHint')}</div>
  <textarea id="ct" rows="5" placeholder="${esc(t('custPh'))}" data-input="custText" style="margin-top:6px">${esc(custText)}</textarea>
  <div class="row"><label class="b">${ic('cam')} ${t('custTake')}<input id="camIn" type="file" accept="image/*" capture="environment" style="display:none" data-change="addImgs"></label>
  <label class="b">${ic('img')} ${t('custPick')}<input id="galIn" type="file" accept="image/*" multiple style="display:none" data-change="addImgs"></label>
  <span class="desc">${custImgs.length}/4</span></div>
  ${custImgs.length?`<div class="row">${custImgs.map((u,i)=>`<div style="position:relative"><img src="${u}" alt="" style="height:84px;border-radius:8px;border:1px solid var(--bd)"><button type="button" class="rmimg" data-click="rmImg" data-i="${i}" aria-label="${esc(t('del'))}"><span>${ic('x')}</span></button></div>`).join('')}</div>`:''}
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
  if(r){custText='';custImgs=[];custOpen=false;set(r);toast(t('custSaved'))}}
let initDone=false;
async function load(){adopt(await fetchState());
  if(!initDone){initDone=true;if(shouldOpenWizard(S))goTab('fridge')}
  render();ensureTr()}
function set(r){if(!r||r.meals===undefined)return;
  mutSeq++;
  if(pending)return;   // w kolejce czekają następne akcje: ekran odświeży odpowiedź ostatniej (stan pośredni tylko by mignął)
  const prevA=S?S.shop_alert||0:0;if((r.shop_alert||0)>prevA)setTimeout(()=>toast(t('shopChanged')),50);
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
  const tb=$('#trbar');tb.textContent=t('bTr');tb.style.display='block';const seq=mutSeq;
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
  setDef:d=>setDef(+d.n),priceOn:d=>priceOn(d.on),priceMap:()=>priceMap(),priceItem:d=>{sheet={kind:'pitem',k:d.k};render()},
  pricePick:d=>pricePick(d.k,d.e),priceSkip:d=>priceSkip(d.k),priceSearch:d=>priceSearch(d.k),undislike:byId(undislike),weekStep:d=>weekStep(+d.d),
  openMenu:()=>openSheet({kind:'menu'}),closeSheet:()=>closeSheet(),setLang:d=>setLang(d.l),setTheme:d=>setTheme(d.th),
  openCook:d=>openCook(d.rid?{rid:+d.rid}:{id:+d.id}),closeCook:()=>closeCook(),cookStep:d=>{cook.i+=+d.d;render();const b=$('#cook .cbody');if(b)b.scrollTop=0},
  cookIng:()=>{cook.ing=!cook.ing;render()},cookDone:()=>cookDone(),rateDislike:d=>{sheet={kind:'meal',id:+d.id,why:true};render()},
  toastAct:()=>toastAct(),confirmYes:()=>{const f=sheet&&sheet.fn;closeSheet();if(f)f()},
  openMeal:byId(openMeal),openRec:d=>openSheet({kind:'rec',id:+d.id}),sheetMeal:d=>openSheet({kind:'meal',id:+d.id}),toggleDone:byId(toggleDone),
  st:d=>{if(sheet&&d.s!=='planned')closeSheet();st(+d.id,d.s)},restoreSwap:d=>st(+d.id,'planned'),retryRec:byId(retryRec),balFix:byId(balFix),
  dislikeAsk:()=>{sheet.why=true;render();const i=$('#panel input[id^=why]');if(i)i.focus()},dislikeCancel:()=>{sheet.why=false;render()},
  dislikeSave:byId(dislikeSave),dislikeOff:byId(dislikeOff),fav:byId(fav),srv:d=>srv(+d.id,numOrNull(d.n)),
  mv2:d=>{closeSheet();mv2(+d.id,d.d)},removeDay:byId(removeDay),carry:d=>{closeSheet();carry(+d.id)},
  goTab:d=>goTab(d.t),goWeek:d=>goWeek(numOrNull(d.id)),confirmPlan:()=>confirmPlan(),delWeek:byId(delWeek),confirmWeek:byId(confirmWeek),
  findAlts:d=>findAlts(+d.id),swapHint:d=>findAlts(+d.id,d.h),closeAlt:byId(closeAlt),toggleAIng:d=>toggleAIng(d.k),choose:d=>choose(+d.id,+d.i),
  togUses:d=>togUses(d.k),addX:()=>addX(),delX:d=>{closeSheet();delX(+d.id)},openX:d=>openSheet({kind:'xitem',id:+d.id}),setAisle:d=>{closeSheet();setAisle(+d.id,d.a)},dismissG:d=>dismissG(d.k),
  openOffers:d=>openSheet({kind:'offers',k:d.k}),offFilter:d=>offFilter(d.c),offNot:d=>offNot(d.k,+d.id),offChainSet:d=>offChainSet(d.c,d.on==='1'),offRefresh:()=>offRefresh(),offPost:()=>offPost(),
  copyList:()=>copyList(),addP:()=>addP(),delP:byId(delP),addC:()=>addC(),delC:byId(delC),gen:()=>gen(),jbAdd:()=>jbAdd(),
  openBook:d=>openSheet({kind:'book',id:+d.id}),togglePick:d=>takeRec(+d.id,!bookPicked().has(+d.id)),useDay:d=>{sheet.day=+d.d;render()},
  useRec:d=>useRec(+d.id,+d.d),delRecAsk:byId(delRecAsk),
  tPick:byId(tPick),tListNew:()=>openSheet({kind:'tlist'}),tListMenu:d=>openSheet({kind:'tlist',id:+d.id}),tNewList:d=>tNewList(d.n),
  tListSave:byId(tListSave),tListDelAsk:byId(tListDelAsk),addT:()=>addT(),openT:byId(openT),tDone:d=>tDone(+d.id,d.on==='1'),
  tMove:d=>tMove(+d.id,+d.i),tStep:d=>tStep(+d.id,d.on==='1'),tStepDel:byId(tStepDel),tStepAdd:byId(tStepAdd),tDueClear:d=>tDue(+d.id,''),
  tToList:d=>tToList(+d.id,+d.l),tRename:()=>tRename(),tRenameSave:byId(tRenameSave),tDelAsk:byId(tDelAsk),
  openKid:d=>openSheet({kind:'kid',id:+d.id,back:d.back==='1'||(sheet&&sheet.kind==='kidweek')}),openKidWeek:()=>openSheet({kind:'kidweek'}),openKidProf:()=>openSheet({kind:'kidprof'}),
  kidMode:d=>kidSet(+d.id,{mode:d.m}),kidPick:d=>kidSet(+d.id,{pick:+d.i}),kidAway:d=>kidSet(+d.id,{away:d.on==='1'}),
  kidExtraAdd:d=>kidSet(+d.id,{extra_add:d.w}),kidExtraDel:d=>kidSet(+d.id,{extra_del:d.w}),kidExtraType:byId(kidExtraType),
  kidMore:byId(kidMore),kidType:()=>{sheet.type=!sheet.type;render();const i=$('#kidtxt');if(i)i.focus()},kidCustom:byId(kidCustom),kidRecipe:byId(kidRecipe),kidDone:()=>kidDone(),
  kidName:()=>kidName(),kidProfSet:d=>kidProf({[d.f]:d.v==='1'}),kidFish:d=>kidProf({fish_max:+d.n}),kidWordAdd:d=>kidWordAdd(d.f),kidWordDel:d=>kidWordDel(d.f,d.w),kidDishDel:d=>kidDishDel(d.w)},
 change:{
  chk:(d,el)=>chk(d.k,el.checked),tDue:(d,el)=>tDue(+d.id,el.value),addImgs:(d,el)=>{addImgs(el.files);el.value=''}},
 enter:{offPost:()=>offPost(),addT:()=>addT(),tNewList:()=>tNewList(),tListSave:byId(tListSave),tStepAdd:byId(tStepAdd),tRenameSave:byId(tRenameSave),findAlts:d=>findAlts(+d.id),dislikeSave:byId(dislikeSave),priceSearch:d=>priceSearch(d.k),addX:()=>addX(),addP:()=>addP(),addC:()=>addC(),jbAdd:()=>jbAdd(),
  kidCustom:byId(kidCustom),kidExtraType:byId(kidExtraType),kidName:()=>kidName(),kidWordAdd:d=>kidWordAdd(d.f)},
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
window.addEventListener('popstate',()=>{
  if(cook&&cook.ing){cook.ing=false;ovPush();render();return}   // „wstecz” przy otwartej liście składników tylko ją zwija
  if(cook){cook=null;wakeOff()}else if(sheet)sheet=null;else return;
  if(S)render()});
document.addEventListener('keydown',e=>{
  if(cook){if(e.key==='Escape'){if(cook.ing){cook.ing=false;render()}else closeCook()}
    else if(e.key==='ArrowRight'||e.key==='ArrowLeft'){const b=$(`#cook [data-click=cookStep][data-d="${e.key==='ArrowRight'?1:-1}"]`);if(b&&!b.disabled)b.click()}
    return}
  if(e.key==='Escape'&&sheet)closeSheet()});
function sheetHead(title){return `<div class="phead"><h2>${title}</h2><button class="hb" data-click="closeSheet" aria-label="${esc(t('close'))}">${ic('x')}</button></div>`}
function sheetBody(){
  if(sheet.kind==='menu')return menuHtml();
  if(sheet.kind==='rate'){const m=gm(sheet.id);   // po „Zrobione” w trybie gotowania: od razu ocena, póki ktoś o niej pamięta
    return `${sheetHead('✓ '+esc(mv(m).name))}<p class="ptxt">${t('rateQ')}</p>
     <button class="act" data-click="fav" data-id="${m.id}" aria-pressed="${!!m.fav}">${ic('fav')} ${m.fav?t('favOn')+' ✓':t('favAdd')}</button>
     ${m.disliked?'':`<button class="act" data-click="rateDislike" data-id="${m.id}">${ic('bad')} ${t('dislikeT')}</button>`}
     <div class="row"><button class="b" data-click="closeSheet">${t('close')}</button></div>`}
  if(sheet.kind==='confirm')return `${sheetHead(esc(sheet.title))}<p class="ptxt">${esc(sheet.text)}</p>
   <div class="row"><button class="b danger" data-click="confirmYes">${esc(sheet.yes)}</button><button class="b" data-click="closeSheet">${t('cancel')}</button></div>`;
  if(sheet.kind==='book')return bookSheet(S.recipes.find(r=>r.id===sheet.id));
  if(sheet.kind==='xitem'){const x=extraItem(sheet.id);   // własny produkt: dział sklepu (poprawka zostaje zapamiętana) i usunięcie
    return `${sheetHead(esc(x.name))}<p class="ptxt">${t('aisleQ')}</p>
     ${AISLES.map(a=>`<button class="act" data-click="setAisle" data-id="${x.extra_id}" data-a="${esc(a)}" aria-pressed="${a===x.aisle}">${esc(t(a))}${a===x.aisle?' ✓':''}</button>`).join('')}
     <div class="row"><button class="b danger" data-click="delX" data-id="${x.extra_id}">${t('del')}</button><button class="b" data-click="closeSheet">${t('close')}</button></div>`}
  if(sheet.kind==='offers')return offersSheet();
  if(sheet.kind==='titem')return tItemSheet();
  if(sheet.kind==='tlist')return tListSheet();
  if(sheet.kind==='pmap')return pmapSheet();
  if(sheet.kind==='pitem')return pitemSheet();
  if(sheet.kind==='kidweek')return kidWeekSheet();
  if(sheet.kind==='kidprof')return kidProfSheet();
  if(sheet.kind==='kid'){const m=gm(sheet.id);return m?kidSheet(m):kidWeekSheet()}
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
  if(sheet&&(!S||((sheet.kind==='rec'||sheet.kind==='meal'||sheet.kind==='rate')&&!gm(sheet.id))||(sheet.kind==='xitem'&&!extraItem(sheet.id))||(sheet.kind==='offers'&&!((shopItem(sheet.k)||{}).offers||[]).length)||(sheet.kind==='titem'&&!tFind(sheet.id))||(sheet.kind==='tlist'&&sheet.id&&!tLists().some(l=>l.id===sheet.id))||(sheet.kind==='book'&&!(S.recipes||[]).some(r=>r.id===sheet.id))))sheet=null;   // danie zniknęło (np. inny tydzień): arkusz nie ma czego pokazać
  box.classList.toggle('open',!!sheet);document.body.classList.toggle('modal',!!(sheet||cook));
  paint($('#panel'),sheet?sheetBody():'')}
function menuHtml(){const dl=S.dislikes||[],dark=document.documentElement.getAttribute('data-theme')==='dark';
  return `${sheetHead(t('menuT'))}<div id="gearbox">
  <div class="mrow"><span>${t('langT')}</span><span class="seg">${['no','pl','en'].map(l=>`<button class="${l===lang?'on':''}" data-click="setLang" data-l="${l}">${l.toUpperCase()}</button>`).join('')}</span></div>
  <div class="mrow"><span>${t('themeT')}</span><span class="seg"><button class="${dark?'':'on'}" data-click="setTheme" data-th="light">${ic('sun')} ${t('thLight')}</button><button class="${dark?'on':''}" data-click="setTheme" data-th="dark">${ic('moon')} ${t('thDark')}</button></span></div>
  <div class="mrow"><span>${t('pDef')}</span><span class="stp"><button class="b" data-click="setDef" data-n="${S.servings_default-1}" aria-label="−">−</button><b>${S.servings_default}</b><button class="b" data-click="setDef" data-n="${S.servings_default+1}" aria-label="+">+</button></span></div>
  ${priceMenu()}
  <button class="act" data-click="openKidProf">${ic('ppl')} ${t('kidProfT')}${kOn()?' · '+esc(S.kid.name):''}</button>
  <div class="msec"><b>${ic('bad')} ${t('dislikesT')}</b> <span class="desc">${t('dislikesSub')}</span>
  ${dl.length?dl.map(d=>`<div class="mrow"><span>${esc(d.name)}${d.reason?` <i>– ${esc(d.reason)}</i>`:''}</span><button class="b" aria-label="${esc(t('restore'))}" data-click="undislike" data-id="${d.id}">${ic('x')}</button></div>`).join(''):`<div class="desc">${t('dislikesNone')}</div>`}</div></div>${offMenu()}
  ${S.week?`<button class="act danger" data-click="delWeek" data-id="${S.week.id}">${ic('del')} ${t('delWeek')} · ${t('wk')}${isoWk(S.week.start)}</button>`:''}`}
function isoWk(ds){const x=new Date(ds+'T12:00:00');x.setDate(x.getDate()+2);const d=new Date(Date.UTC(x.getFullYear(),x.getMonth(),x.getDate()));const n=d.getUTCDay()||7;d.setUTCDate(d.getUTCDate()+4-n);const y=new Date(Date.UTC(d.getUTCFullYear(),0,1));return Math.ceil(((d-y)/864e5+1)/7)}
/* --- nagłówek: jedna linia. Na zakładkach tygodnia i zakupów tydzień ze strzałkami ‹ ›, na pozostałych nazwa zakładki. */
function weekNb(d){const ws=[...((S&&S.weeks)||[])].sort((a,b)=>a.start<b.start?-1:1),i=S&&S.week?ws.findIndex(w=>w.id===S.week.id):-1;return i<0?null:ws[i+d]||null}
function weekStep(d){const w=weekNb(d);if(w)goWeek(w.id===S.current_id?null:w.id,true)}
function headRender(){
  const w=S&&S.week,wk=(tab==='plan'||tab==='shop')&&w;let h;
  if(wk){const tag=w.id!==S.current_id?(w.start>S.today?t('upcoming'):t('archBan')).replace(':',''):'';
    h=`<b>${t('week')} ${isoWk(w.start)} · ${dm(w.start)}–${dm(w.end)}</b>${tag?`<small>${tag}</small>`:''}`}
  else h=`<b>${tab==='fridge'?t('tabW'):tab==='book'?t('tabB'):tab==='todo'?t('todoT'):'Ukesmeny'}</b>`;
  const r=$('#range');if(r._h!==h){r._h=h;r.innerHTML=h}
  [['#wkPrev',-1,'prevWk'],['#wkNext',1,'nextWkA']].forEach(([q,d,k])=>{const b=$(q);b.hidden=!wk;b.disabled=!weekNb(d);b.setAttribute('aria-label',t(k))});
  $('#gear').setAttribute('aria-label',t('menuA'))}
/* --- dolny pasek zakładek; przy zakupach licznik pozycji, które zostały do kupienia */
const TABS=[['plan','tabWk'],['shop','tabS'],['fridge','tabW'],['book','tabB'],['todo','tabT']];
function shopLeft(){let n=0;for(const g of Object.values((S&&S.shopping)||{}))for(const i of g)if(!i.checked)n++;return n}
function navRender(){
  TABS.forEach(([k,l])=>{const b=$('#n_'+k);b.querySelector('span').textContent=t(l);b.classList.toggle('on',tab===k);
    if(tab===k)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  const n=shopLeft(),c=$('#n_cnt');c.textContent=n||'';c.hidden=!n;c.classList.toggle('alert',!!(S&&S.shop_alert>0))}
let forceRender=false;
const wideMq=matchMedia('(min-width:900px)');
wideMq.addEventListener('change',()=>{if(S)render()});
function render(){
  headRender();navRender();
  // Listę przebudowujemy tylko wtedy, gdy jej treść się zmieniła (patrz paint). Odświeżenie w tle, które nic nie zmienia,
  // nie podmienia więc elementu pod palcem (dotknięcie trwające w chwili podmiany przepadało). forceRender wymusza
  // przebudowę, gdy trzeba cofnąć coś, co zmieniło się tylko na ekranie (zaznaczone pole po nieudanym zapisie).
  // szeroki ekran (od 900 px): tydzień w siatce siedmiu dni, a lista zakupów w bocznej kolumnie; ten sam HTML co na telefonie
  const wide=wideMq.matches&&tab==='plan'&&!!S.week,main=$('#main');main.classList.toggle('w',wide);
  paint(main,wide?`<div class="wide"><div class="wcol">${plan()}</div><aside class="side">${shop()}</aside></div>`
    :tab==='plan'?plan():tab==='shop'?shop():tab==='book'?book():tab==='todo'?todo():fridge(),forceRender);forceRender=false;
  renderCook();renderSheet();
  if(tab==='fridge')wizSync();
  schedulePoll()}
function needPoll(){return S&&S.meals&&((S.offers&&S.offers.busy)||S.meals.some(m=>m.filling||m.kid_busy||(m.alts&&m.alts.length===0&&!m.loading)))}
function schedulePoll(){if(pollT||!needPoll())return;pollT=setTimeout(async()=>{pollT=null;if(drag||pending){schedulePoll();return}
  const seq=mutSeq;
  try{const r=await fetch('/api/state'+wq());if(r.ok){const d=await r.json();
    if(drag||pending||seq!==mutSeq){schedulePoll();return}   // w trakcie pobierania poszła akcja: ta odpowiedź może być sprzed niej
    const waiting=new Set(S.meals.filter(m=>m.alts&&m.alts.length===0).map(m=>m.id));
    adopt(d);const ready=d.meals.filter(m=>waiting.has(m.id)&&m.alts&&m.alts.length>0).map(m=>m.id);
    render();ready.forEach(attention);return}}catch(e){}render()},2500)}
function ingList(names){return `<ul>${names.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`}
/* --- tydzień: jeden wiersz na dzień (data, nazwa, kółko „zrobione”). Data jest uchwytem do przeciągania, dotknięcie
   nazwy otwiera przepis, a rzadkie akcje są w arkuszu pod ⋯. Dzisiejszy dzień jest rozwinięty i ma to samo kółko co reszta. */
function mealState(m){   // dopisek pod nazwą, tylko gdy z daniem coś się dzieje
  if(m.loading||(m.alts&&m.alts.length===0))return '⏳ '+t('bSwap');
  if(m.alts&&m.alts.length)return t('readyT');
  if(m.draft&&m.filling)return '⏳ '+t('recWait');
  if(m.draft&&(m.draft_error||S.week.confirmed))return '⚠ '+t('recNone');
  if(m.overdue&&m.status==='planned')return '⚠ '+t('overdueS');
  return ''}
function mealCard(m){const v=mv(m),id=m.id,isT=m.date===S.today,done=m.status==='done';
  const d=`<span class="d handle"><small>${esc(isT?t('today'):t('daysS')[m.day])}</small><b>${m.date.slice(8)}</b></span>`;
  const more=`<button class="mb" data-click="sheetMeal" data-id="${id}" aria-label="${esc(t('actions'))}">${ic('more')}</button>`;
  if(m.status==='removed')return `<div class="meal off" data-id="${id}"><div class="dr">${d}
   <button class="nmb" data-click="sheetMeal" data-id="${id}"><span class="name">${t('dayOffS')}</span><span class="desc"><s>${esc(v.name)}</s></span></button>
   <button class="mb" data-click="st" data-id="${id}" data-s="planned" aria-label="${esc(t('restore'))}" title="${esc(t('restore'))}">${ic('undo')}</button></div></div>`;
  let sub=[mealState(m),...(isT?[m.time_min?m.time_min+' min':'',m.servings_eff+' '+t('por'),m.is_fish?t('fish'):'']:[]),
    m.status==='skipped'?t('tSkip'):'',m.owned?t('tCarry'):'',m.bal&&m.bal.level==='none'?t('balNoneS'):''].filter(Boolean).map(esc).join(' · ').replace(/^⏳ /,ic('wait')+' ').replace(/^⚠ /,ic('warn')+' ');
  if(isT&&done)sub=`<b>${esc(t('tDoneT'))}</b>`+(sub?' · '+sub:'');   // dziś: stan także słowem, nie tylko kółkiem
  const ck=`<button class="ck ${done?'on':''}" data-click="toggleDone" data-id="${id}" aria-pressed="${done}" aria-label="${esc(t('markDoneA'))}"></button>`;
  return `<div class="meal ${done?'done':''} ${m.overdue&&m.status==='planned'?'late':''}" data-id="${id}"><div class="dr">${d}
   <button class="nmb" data-click="openMeal" data-id="${id}"><span class="name">${esc(v.name)}</span>${sub?`<span class="desc">${sub}</span>`:''}</button>
   ${isT?ck:more+ck}</div>${kidRow(m)}
   ${isT?`<div class="tr">${m.draft?`<button class="b p" data-click="openMeal" data-id="${id}">${ic('book')} ${t('recipe')}</button>`:`<button class="b ${done?'':'p'}" data-click="openCook" data-id="${id}">${ic('pot')} ${t('cookBtn')}</button>`}
    <span class="sp"></span>${more}</div>`:''}</div>`}
/* --- plan dziecka: wiersz pod daniem dorosłych, krok „dziecko w tym tygodniu” po zatwierdzeniu planu, wybór na dzień
   („to samo” albo własne proste danie z propozycji, dodatek tylko dla dziecka), profil w ustawieniach. Działa tylko z włączonym profilem. */
const kOn=()=>!!(S&&S.kid&&S.kid.on);
const kTag=()=>`<i class="kt">${esc(S.kid.name)}</i>`;
const kOwn=k=>!!(k&&k.mode==='own'&&k.pick);
const kExtras=k=>k&&k.extras.length?'+ '+k.extras.map(i=>esc(nm(i.name))).join(', '):'';
function kidNote(x){return [x.is_new?`<i class="kt">${t('kidNew')}</i>`:'',[x.shares?esc(t('kidShare').replace('{x}',nm(x.shares))):'',x.extra_min?'+'+x.extra_min+' min':''].filter(Boolean).join(' · ')].join('')}
function kidRow(m){if(!kOn()||!S.week.confirmed)return '';
  const k=m.kid,open=`data-click="openKid" data-id="${m.id}"`;
  if(!k&&!m.kid_busy)return '';   // dawny tydzień sprzed planu dziecka: nic o niej nie wiemy, wiersz byłby pusty
  if(kOwn(k)&&!k.away)return `<button class="kr own" ${open}><span class="kn"><span class="kname">${esc(k.pick.name)}</span><span class="kl">${kTag()}${[kidNote(k.pick),kExtras(k)].filter(Boolean).join(' · ')}</span></span></button>`;
  const same=t('kidSame').toLowerCase(),txt=!k?(m.kid_busy?t('kidWait'):same):k.away?t('kidAway').toLowerCase():[same,kExtras(k)].filter(Boolean).join(' · ');
  return `<button class="kr" ${open}><span class="kl">${kTag()}${txt}</span></button>`}
function kidRecBox(m){if(!kOn()||!S.week.confirmed||!m.kid||m.kid.away)return '';
  const k=m.kid;
  return `<div class="kbox"><b>${esc(t('kidExtraL').replace('{n}',S.kid.name))}</b>${kOwn(k)?`<div class="desc">${t('kidOwn')}: ${esc(k.pick.name)}</div>`:''}
   ${k.extras.length?`<ul class="ings">${k.extras.map(i=>`<li>${esc(i.qty??'')} ${esc(i.unit)} ${esc(nm(i.name))}</li>`).join('')}</ul>`:''}
   <div class="row"><button class="b" data-click="openKid" data-id="${m.id}">${ic('plus')} ${t('kidExtraAddB')}</button></div></div>`}
function kidWeekSheet(){const D=t('days'),n=S.kid.name;
  return `${sheetHead(esc(t('kidWeekT').replace('{n}',n)))}<div class="desc">${esc(t('kidWeekSub').replace('{n}',n))}</div>
  ${S.meals.filter(m=>m.status!=='removed').map(m=>{const k=m.kid,own=kOwn(k);
    return `<div class="kday" data-kid="${m.id}"><div><b>${esc(D[m.day])}</b> · ${esc(mv(m).name)}</div>
     ${k&&k.away?'':`<div class="chips"><button class="chip ${own?'':'on'}" data-click="kidMode" data-id="${m.id}" data-m="same" aria-pressed="${!own}">${t('kidSame')}</button><button class="chip ${own?'on':''}" data-click="kidMode" data-id="${m.id}" data-m="own" aria-pressed="${own}" ${k&&(k.pick||k.props.length)?'':'disabled'}>${t('kidOwn')}</button></div>`}
     <button class="kmore" data-click="openKid" data-id="${m.id}" data-back="1"><span>${!k?(m.kid_busy?ic('wait')+' '+t('kidWait'):''):k.away?t('kidAway'):[own?esc(k.pick.name):'',kExtras(k)].filter(Boolean).join(' · ')||t('kidExtraAddB')}</span><span>${k&&k.last?t('kidLast')+' ':''}›</span></button></div>`}).join('')}
  <div class="row"><button class="b p" data-click="kidDone">${t('kidDoneB')}</button><button class="b" data-click="closeSheet">${t('later')}</button></div>`}
function kidSheet(m){const k=m.kid,id=m.id,own=kOwn(k),hints=(S.kid_extras||[]).filter(x=>!(k&&k.extras.some(i=>i.name.toLowerCase()===x.toLowerCase())));
  const head=`${sheetHead(esc(S.kid.name+' · '+t('days')[m.day]))}<div class="desc">${t('kidYou')}: ${esc(mv(m).name)}</div>
   ${sheet.back?`<button class="lnk" data-click="openKidWeek">‹ ${t('kidWeekBack')}</button>`:''}`;
  const custom=`<div class="row"><button class="b" data-click="kidMore" data-id="${id}">${t('kidMoreB')}</button><button class="b" data-click="kidType">${t('kidTypeB')}</button></div>
   ${sheet.type?`<div class="inrow"><input id="kidtxt" placeholder="${esc(t('kidTypePh'))}" data-enter="kidCustom" data-id="${id}" autocomplete="off"><button class="b p" data-click="kidCustom" data-id="${id}">${t('add')}</button></div>`:''}`;
  const dish=own?`<h3>${esc(k.pick.name)}</h3><ul class="ings">${k.pick.ingredients.map(i=>i.shared?`<li>${esc(nm(i.name))} <span class="desc">(${t('kidFromYours')})</span></li>`:`<li>${esc(i.qty??'')} ${esc(i.unit)} ${esc(nm(i.name))}</li>`).join('')}</ul>
   ${k.pick.steps.length?`<ol class="steps">${k.pick.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol>`:`<div class="row"><button class="b" data-click="kidRecipe" data-id="${id}">${ic('pen')} ${t('kidRecB')}</button></div>`}`:'';
  return `${head}
   <button class="kopt" data-click="kidMode" data-id="${id}" data-m="same" aria-pressed="${!own}"><span class="rb ${own?'':'on'}"></span><span class="li"><b>${t('kidSameL')}</b><span class="desc">${t('kidSameD')}</span></span></button>
   <div class="kopt"><span class="rb ${own?'on':''}"></span><div class="li"><b>${t('kidOwnL')}</b><span class="desc">${t('kidOwnD')}</span>
    ${!k&&m.kid_busy?`<div class="note">${ic('wait')} ${t('kidWait')}</div>`:''}${k&&k.error&&!k.props.length?`<div class="note">${t('kidErr')}</div>`:''}
    ${(k?k.props:[]).map((x,i)=>`<button class="pr3 ${own&&k.pick.name===x.name?'on':''}" data-click="kidPick" data-id="${id}" data-i="${i}" aria-pressed="${own&&k.pick.name===x.name}"><span class="kname">${esc(x.name)}</span><span class="desc">${kidNote(x)}</span></button>`).join('')}
    ${custom}</div></div>
   ${dish}
   <div class="lbl">${esc(t('kidExtraL').replace('{n}',S.kid.name))}</div>
   <div class="chips">${(k?k.extras:[]).map(i=>`<button class="chip on" data-click="kidExtraDel" data-id="${id}" data-w="${esc(i.name)}">${esc(nm(i.name))} ×</button>`).join('')}${hints.map(x=>`<button class="chip" data-click="kidExtraAdd" data-id="${id}" data-w="${esc(x)}">${esc(nm(x))}</button>`).join('')}</div>
   <div class="inrow"><input id="kidex" placeholder="${esc(t('kidExtraPh'))}" data-enter="kidExtraType" data-id="${id}" autocomplete="off"><button class="b" data-click="kidExtraType" data-id="${id}" aria-label="${esc(t('add'))}">+</button></div>
   <div class="desc" style="margin-top:6px">${t('kidExtraD')}</div>
   <div class="mrow" style="border:0"><span>${t('kidAwayL')}</span>${kSw('kidAway',!!(k&&k.away),`data-id="${id}"`)}</div>`}
const kSw=(act,on,extra)=>`<button class="sw ${on?'on':''}" role="switch" aria-checked="${on}" data-click="${act}" data-on="${on?0:1}" data-v="${on?0:1}" ${extra||''}></button>`;
function kidProfSheet(){const p=S.kid,ds=S.kid_dishes||[];
  const words=f=>`<div class="chips">${p[f].map(w=>`<button class="chip" data-click="kidWordDel" data-f="${f}" data-w="${esc(w)}">${esc(w)} ×</button>`).join('')}</div>
   <div class="inrow"><input id="kid_${f}" placeholder="${esc(t('kidWordPh'))}" data-enter="kidWordAdd" data-f="${f}" autocomplete="off"><button class="b" data-click="kidWordAdd" data-f="${f}" aria-label="${esc(t('add'))}">+</button></div>`;
  return `${sheetHead(t('kidProfT'))}
   <div class="inrow"><input id="kidname" value="${esc(p.name)}" placeholder="${esc(t('kidNamePh'))}" data-enter="kidName" autocomplete="off"><button class="b p" data-click="kidName">${t('save')}</button></div>
   <div class="mrow"><span>${t('kidOnL')}</span>${kSw('kidProfSet',p.on,'data-f="on"')}</div>
   <div class="lbl">${t('kidLikes')}</div>${words('likes')}
   <div class="lbl">${t('kidDislikes')}</div>${words('dislikes')}
   <div class="lbl">${t('kidDishes')}</div>${ds.length?ds.map(d=>`<div class="mrow"><span>${esc(d.name)}</span><button class="mb" data-click="kidDishDel" data-w="${esc(d.name)}" aria-label="${esc(t('del'))}">${ic('x')}</button></div>`).join(''):`<div class="desc">${t('kidDishesNone')}</div>`}
   <div class="mrow"><span>${t('kidFishL')}</span><span class="stp"><button class="b" data-click="kidFish" data-n="${p.fish_max-1}" aria-label="−" ${p.fish_max<=0?'disabled':''}>−</button><b>${p.fish_max}</b><button class="b" data-click="kidFish" data-n="${p.fish_max+1}" aria-label="+" ${p.fish_max>=7?'disabled':''}>+</button></span></div>
   <div class="mrow"><span>${t('kidMeatL')}</span>${kSw('kidProfSet',p.meat,'data-f="meat"')}</div>
   <div class="mrow" style="border:0"><span>${t('kidNovL')}</span>${kSw('kidProfSet',p.novelty,'data-f="novelty"')}</div>`}
async function kidSet(id,body){const r=await api(`/api/meal/${id}/kid`,'POST',body);if(r)set(r)}
async function kidMore(id){const r=await api(`/api/meal/${id}/kid/more`,'POST',undefined,t('kidThinking'));if(r)set(r)}
async function kidCustom(id){const v=(($('#kidtxt')||{}).value||'').trim();if(v.length<2)return;
  const r=await api(`/api/meal/${id}/kid/custom`,'POST',{text:v},t('kidThinking'));if(r){if(sheet)sheet.type=false;set(r)}}
async function kidRecipe(id){const r=await api(`/api/meal/${id}/kid/recipe`,'POST',undefined,t('kidRecWait'));if(r)set(r)}
function kidExtraType(id){const i=$('#kidex'),v=((i||{}).value||'').trim();if(!v)return;i.value='';kidSet(id,{extra_add:v})}
async function kidDone(){closeSheet();const r=await api('/api/week/kid_done','POST',W({}));if(r)set(r)}
function kidAfterConfirm(){if(kOn()&&S.week&&S.week.confirmed&&!S.week.kid_step)openSheet({kind:'kidweek'})}
async function kidProf(body){const r=await api('/api/kid/profile','POST',W(body));if(r)set(r)}
function kidName(){const v=(($('#kidname')||{}).value||'').trim();if(!v){toast(t('kidNeedName'));return}kidProf(S.kid.name?{name:v}:{name:v,on:true})}
function kidWordAdd(f){const i=$('#kid_'+f),add=((i||{}).value||'').split(',').map(x=>x.trim()).filter(Boolean);if(!add.length)return;i.value='';kidProf({[f]:[...S.kid[f],...add]})}
function kidWordDel(f,w){kidProf({[f]:S.kid[f].filter(x=>x!==w)})}
async function kidDishDel(w){const r=await api('/api/kid/dish/delete','POST',W({name:w}));if(r)set(r)}
function plan(){
  if(!S.week)return `<div class="card">${t('noplan')}<div class="row"><button class="b p" data-click="goTab" data-t="fridge">${t('goPlanner')}</button></div></div>`;
  let h='';
  if(S.week.id!==S.current_id)h+=`<div class="strip"><span>${(S.week.start>S.today?t('upcoming'):t('archBan')).replace(':','')}</span><button class="b" data-click="goWeek" data-id="">${t('backCur')}</button></div>`;
  if(S.carry.length)h+=`<div class="warn">${t('waiting')} ${S.carry.map(esc).join(', ')}</div>`;
  if(kOn()&&S.week.confirmed&&!S.week.kid_step)h+=`<div class="strip kstrip"><span>${esc(t('kidStrip').replace('{n}',S.kid.name))}</span><button class="b" data-click="openKidWeek">${t('kidChoose')}</button></div>`;
  if(S.week.confirmed===false)h+=`<div class="warn" style="background:var(--info);border-color:var(--infobd)"><b>${t('confTitle')}</b><div class="desc" style="margin-top:4px">${t('confTxt')}</div><div class="row"><button class="b p" data-click="confirmPlan">${t('confirmBtn')}</button></div></div>`;
  h+='<div class="week">'+S.meals.map(m=>`<div class="slot ${m.date===S.today?'today':''} ${m.date<S.today?'past':''} ${m.status==='removed'?'offday':''}" data-day="${m.day}">${mealCard(m)}</div>`).join('')+'</div>'+balWeek();
  return h}
/* --- tryb gotowania: pełny ekran, jeden krok dużym tekstem, „Wstecz / Dalej”. Przycisk „Wszystkie składniki” jest na
   każdym kroku i rozwija pełną listę z ilościami nad krokiem, bez wychodzenia z niego. Ekran nie gaśnie (Wake Lock),
   o ile przeglądarka na to pozwala; odmowa albo brak API niczego nie psuje. cook = {id dania | rid przepisu, i, ing}. */
let wakeLock=null;
async function wakeOn(){
  try{if(wakeLock||!cook||!('wakeLock' in navigator))return;
    const w=await navigator.wakeLock.request('screen');
    if(!cook){w.release().catch(()=>{});return}
    wakeLock=w;w.addEventListener('release',()=>{if(wakeLock===w){wakeLock=null;if(cook)renderCook()}});renderCook()}
  catch(e){wakeLock=null}}
function wakeOff(){const w=wakeLock;wakeLock=null;if(w)w.release().catch(()=>{})}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&cook)wakeOn()});   // system zwalnia blokadę, gdy karta znika z ekranu
function cookSrc(){
  if(cook.rid!=null){const r=(S.recipes||[]).find(x=>x.id===cook.rid);if(!r)return null;const v=rv(r);
    return {name:v.name,steps:v.steps,ings:r.ingredients.map((i,k)=>`${i.qty??''} ${i.unit} ${v.ing[k]||i.name}`),por:null,meal:null}}
  const m=gm(cook.id);if(!m||m.draft)return null;const v=mv(m);
  return {name:v.name,steps:v.steps,ings:m.ingredients.map((i,k)=>`${m.qv[k]??''} ${i.unit} ${v.ing[k]||i.name}`),por:m.servings_eff,meal:m}}
function openCook(x){sheet=null;cook={...x,i:0,ing:false};ovPush();render();wakeOn()}
function closeCook(){if(!cook)return;cook=null;wakeOff();render();ovPop()}
function renderCook(){const el=$('#cook'),c=cook&&S?cookSrc():null;
  if(cook&&(!c||!c.steps.length)){cook=null;wakeOff()}
  el.classList.toggle('open',!!cook);
  if(!cook){paint(el,'');return}
  const n=c.steps.length,i=cook.i=Math.max(0,Math.min(cook.i,n-1)),last=i===n-1;
  paint(el,`<div class="chead"><button class="hb" data-click="closeCook" aria-label="${esc(t('close'))}">${ic('x')}</button><b>${esc(c.name)}</b>${c.por?`<span>${c.por} ${t('por')}</span>`:''}</div>
   <div class="pbar"><i style="width:${Math.round(100*(i+1)/n)}%"></i></div>
   <div class="cbar"><button class="b p" data-click="cookIng" aria-expanded="${cook.ing}">${ic('ing')} ${t('allIng')} ${ic(cook.ing?'chu':'chd')}</button><span class="sp"></span>${wakeLock?`<span class="desc awake">${ic('sun')} ${t('awake')}</span>`:''}</div>
   ${cook.ing?`<div class="cing"><ul class="ings">${c.ings.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:''}
   <div class="cbody"><div class="cstepn">${t('stepN').replace('{a}',i+1).replace('{b}',n)}</div><div class="cstep">${esc(c.steps[i])}</div>
    ${last?'':`<div class="cnext desc">${t('nextS')}: ${esc(c.steps[i+1])}</div>`}</div>
   <div class="cnav"><button class="b" data-click="cookStep" data-d="-1" ${i?'':'disabled'}>${ic('chl')} ${t('back')}</button>
    ${!last?`<button class="b p" data-click="cookStep" data-d="1">${t('next')} ${ic('chr')}</button>`
     :c.meal&&c.meal.status!=='done'?`<button class="b p" data-click="cookDone">${t('markDone')}</button>`:`<button class="b p" data-click="closeCook">${t('close')}</button>`}</div>`)}
// Ostatni krok: „Zrobione” odhacza dzień i od razu pyta o ocenę (⭐ albo 👎).
async function cookDone(){const id=cook&&cook.id;closeCook();if(id==null)return;
  const r=await api(`/api/meal/${id}/status`,'POST',{status:'done'});if(!r)return;set(r);
  if(gm(id))openSheet({kind:'rate',id});else toast('✓ '+t('doneT'))}
function openMeal(id){const m=gm(id);if(!m)return;
  openSheet({kind:m.status==='removed'||m.overdue||m.loading||m.alts!=null?'meal':'rec',id})}   // gdy danie czeka na decyzję, od razu arkusz akcji
// Podgląd przepisu (dotknięcie wiersza). Szkic bez przepisu pokazuje same nazwy składników i, gdy nikt go nie pisze, przycisk „Napisz przepis”.
// Bilans talerza, celowo dyskretnie: jeden szary wiersz pod opisem dania. Przycisk „Popraw danie” tylko wtedy,
// gdy białka brakuje albo jest go mało, a danie ma już przepis.
const balKind=k=>t(`bk_${k}`);   // rodzaj źródła białka z serwera (legume, tofu, egg, cheese, dairy, fish, sub, nuts)
function balLine(m){const b=m.bal;if(!b||!b.level)return '';
  const g=b.g!=null?' · '+t('balG').replace('{g}',b.g):'',k=b.kinds.map(balKind).join(', ');
  if(b.level==='ok')return `<div class="desc bal">${esc(t('balT')+': '+k+g)}</div>`;
  return `<div class="desc bal"><span>${esc(t(b.level==='none'?'balNone':'balLow')+(k?' ('+k+')':'')+g)}</span>${m.draft?'':`<button class="lnk" data-click="balFix" data-id="${m.id}">${t('balFix')}</button>`}</div>`}
// Źródła białka w całym tygodniu (główne źródło każdego dania), jeden szary wiersz pod listą dni.
function balWeek(){const n={};S.meals.forEach(m=>{const k=m.status!=='removed'&&m.bal&&m.bal.kinds[0];if(k)n[k]=(n[k]||0)+1});
  const ks=Object.keys(n).sort((a,b)=>n[b]-n[a]);
  return ks.length?`<div class="desc balw">${esc(t('balWeek')+': '+ks.map(k=>balKind(k)+' '+n[k]).join(' · '))}</div>`:''}
function recSheet(m){const v=mv(m),id=m.id;let body;
  if(m.draft){
    body=m.filling?`<div class="note">${ic('wait')} ${t('recWait')}</div>`
     :(m.draft_error||S.week.confirmed)?`<div class="note">${t('recNone')}</div><div class="row"><button class="b p" data-click="retryRec" data-id="${id}">${ic('pen')} ${t('recWrite')}</button></div>`:'';
    body+=`<h3>${t('sectIng')}</h3>${ingList(m.ingredient_names||[])}`;
  }else body=`<h3>${t('sectIng')}</h3><ul class="ings">${m.ingredients.map((i,k)=>`<li>${esc(m.qv[k]??'')} ${esc(i.unit)} ${esc(v.ing[k]||i.name)}</li>`).join('')}</ul>
   ${kidRecBox(m)}<h3>${t('sectStp')}</h3><ol class="steps">${v.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol>
   ${okUrl(m.source)?`<a class="lnk" href="${esc(m.source)}" target="_blank" rel="noopener">${t('src')} ↗</a>`:''}`;
  return `${sheetHead(esc(v.name))}<div class="desc">${[v.description,m.time_min?m.time_min+' min':'',m.servings_eff+' '+t('por'),m.is_fish?t('fish'):''].filter(Boolean).map(esc).join(' · ')}</div>${balLine(m)}
   <div class="row">${m.draft?'':`<button class="b p" data-click="openCook" data-id="${id}">${ic('pot')} ${t('cookBtn')}</button>`}<button class="b" data-click="sheetMeal" data-id="${id}">${ic('more')} ${t('actions')}</button></div>
   ${body}`}
// Arkusz akcji dania: zamiana (podpowiedzi, własne życzenie, propozycje), przeniesienie, porcje, przepisy, 👎, usunięcie.
function mealSheet(m){const v=mv(m),id=m.id,D=t('days');
  const head=sheetHead(esc(v.name))+`<div class="desc">${esc(D[m.day])} ${dm(m.date)}</div>`;
  const move=`<div class="lbl">${ic('move')} ${t('moveBtn')}</div><div class="chips">${t('daysS').map((x,k)=>k===m.day?'':`<button class="chip" data-click="mv2" data-id="${id}" data-d="${k}" aria-label="${esc(D[k])}">${esc(x)}</button>`).join('')}</div>`;
  if(m.status==='removed')return `${sheetHead(t('dayOffS'))}<div class="desc">${esc(D[m.day])} ${dm(m.date)} · <s>${esc(v.name)}</s></div>
   <button class="act" data-click="st" data-id="${id}" data-s="planned">${ic('undo')} ${t('restore')}</button>
   <button class="act" data-click="restoreSwap" data-id="${id}">${ic('swap')} ${t('otherDish')}</button>${move}`;
  const dis=m.disliked?`<button class="act" data-click="dislikeOff" data-id="${id}" aria-label="dislike" aria-pressed="true">${ic('bad')} ${t('dislikeT')} ✓ <span class="desc">${t('undo')}</span></button>`
   :sheet.why?`<div class="alt"><b>${ic('bad')} ${t('dislikeT')}</b><div class="desc">${t('dislikeQ')}</div>
     <div class="inrow"><input id="why${id}" placeholder="${esc(t('dislikePh'))}" data-enter="dislikeSave" data-id="${id}"><button class="b p" data-click="dislikeSave" data-id="${id}">${t('save')}</button></div>
     <div class="row"><button class="b" data-click="dislikeCancel">${t('cancel')}</button></div></div>`
   :`<button class="act" data-click="dislikeAsk" aria-label="dislike" aria-pressed="false">${ic('bad')} ${t('dislikeT')}</button>`;
  // zaległe danie (dzień minął, a nie jest odhaczone): decyzja na górze arkusza
  const late=m.overdue?`<div class="note"><b>${t('overdueQ')}</b><div class="row"><button class="b p" data-click="st" data-id="${id}" data-s="done">${t('markDone')}</button>
    <button class="b" data-click="carry" data-id="${id}">${t('carry')}</button><button class="b" data-click="st" data-id="${id}" data-s="skipped">${t('skip')}</button></div></div>`:'';
  return `${head}${late}<button class="act" data-click="openRec" data-id="${id}">${ic('book')} ${t('recipe')}</button>
   ${m.status==='planned'||m.alts!=null||m.loading?`<div id="alt${id}">${altsHtml(m)}</div>`:''}${move}
   <div class="mrow"><span>${ic('ppl')} ${t('porT')}</span><span class="stp"><button class="b" data-click="srv" data-id="${id}" data-n="${m.servings_eff-1}" aria-label="−">−</button><b>${m.servings_eff}</b><button class="b" data-click="srv" data-id="${id}" data-n="${m.servings_eff+1}" aria-label="+">+</button>${m.servings?`<button class="b" data-click="srv" data-id="${id}" data-n="" aria-label="${esc(t('restore'))}">${ic('undo')}</button>`:''}</span></div>
   <button class="act" data-click="fav" data-id="${id}" aria-label="favorite" aria-pressed="${!!m.fav}">${ic('fav')} ${m.fav?t('favOn')+' ✓':t('favAdd')}</button>
   ${dis}
   ${m.status==='planned'?`<button class="act danger" data-click="removeDay" data-id="${id}">${ic('del')} ${t('removeDayL')}</button>`:''}`}
const SWAPS=['swRice','swLight','swQuick'];
function altsHtml(m){const id=m.id;
  if(m.loading||(m.alts&&m.alts.length===0))return `<div class="altwrap" id="aw${id}"><div class="finding"><div class="spinner"></div><div><div class="ft">${t('bSwap')}</div><div class="fs">${t('findSub')}</div></div></div><div class="row"><button class="b" data-click="closeAlt" data-id="${id}">${t('cancel')}</button></div><div class="skel"></div><div class="skel"></div></div>`;
  const ask=`<div class="inrow"><input id="hint${id}" placeholder="${esc(t('askPh'))}" value="${esc(m.hint||'')}" data-enter="findAlts" data-id="${id}"><button class="b p" data-click="findAlts" data-id="${id}">${t('find')}</button></div>`;
  // jeszcze nic nie szukano: gotowe podpowiedzi jednym dotknięciem albo własne życzenie
  if(!m.alts)return `<div class="swap"><div class="lbl">${ic('swap')} ${t('swapBtn')}</div><div class="chips">${SWAPS.map(k=>`<button class="chip" data-click="swapHint" data-id="${id}" data-h="${esc(t(k))}">${t(k)}</button>`).join('')}<button class="chip" data-click="swapHint" data-id="${id}" data-h="">${ic('plan')} ${t('surprise')}</button></div>${ask}</div>`;
  return `<div class="altwrap ${m.justReady?'ready':''}" id="aw${id}"><div class="${m.justReady?'readyb':'lbl'}">${t('readyT')}${m.justReady?' ↓':''}</div>`+m.alts.map((o,i)=>{const k=id+':'+i,op=!!openAIng[k];return `<div class="alt"><b>${esc(o.name)}</b><div class="desc">${esc(o.description)}</div>
  ${(o.ingredients||[]).length?`<button class="lnk" data-click="toggleAIng" data-k="${k}">${op?t('hideIng')+' '+ic('chu'):t('showIng')+' '+ic('chd')}</button>${op?ingList(o.ingredients):''}`:''}
  <div class="row"><button class="b p" ${m.choosing!=null?'disabled':''} data-click="choose" data-id="${id}" data-i="${i}">${m.choosing===i?ic('wait'):t('choose')}</button></div></div>`}).join('')+
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
  const dish=m?rv(m).name:'',who=u.kid!==undefined&&S.kid?S.kid.name:'';   // składnik dziecka: jej własne danie albo dodatek do dania dorosłych
  return `${esc(t('daysS')[u.day])} · ${esc(u.kid?u.kid:who?dish+' · '+who:dish)}${q}`}
// W ilu daniach jest produkt. Jedno danie: sama linia. Kilka: linia z dniami, a szczegóły z ilościami rozwija przycisk ▾ na końcu wiersza.
function usesHtml(i,k){const u=i.uses||[];if(!u.length)return '';
  if(u.length===1)return `<div class="use">${useLine(u[0])}</div>`;
  return `<div class="use">${t('usedIn').replace('{n}',u.length)}: ${u.map(x=>esc(t('daysS')[x.day])).join(', ')}</div>`+(usesOpen.has(k)?u.map(x=>`<div class="use">${useLine(x,true)}</div>`).join(''):'')}
function usesBtn(i,k){return (i.uses||[]).length>1?`<button type="button" class="mb" data-click="togUses" data-k="${esc(k)}" aria-label="${esc(t('usesA'))}" aria-expanded="${usesOpen.has(k)}">${ic(usesOpen.has(k)?'chu':'chd')}</button>`:''}
function headsTxt(i){if(!i.heads)return '';const w=t('heads');return ` <span class="use" style="text-decoration:none">(≈ ${i.heads} ${i.heads===1?w[0]:w[1]})</span>`}
function shopRow(i){return `<label class="${i.checked?'c':''}"><input type="checkbox" ${i.checked?'checked':''} data-change="chk" data-k="${esc(i.key)}"><div class="li"><span>${i.topup?'<b>+ </b>':''}${esc(i.qty)} ${esc(i.unit)} ${esc(i.extra_id?i.name:nm(i.name))}</span>${headsTxt(i)}${i.topup?` <span class="tag" style="background:var(--badbg);color:var(--bad)">${t('buyMore')}</span>`:''}${usesHtml(i,i.key)}</div>${offBtn(i)}${usesBtn(i,i.key)}${i.extra_id?`<button type="button" class="mb" data-click="openX" data-id="${i.extra_id}" aria-label="${esc(t('more'))}">${ic('more')}</button>`:''}</label>`}
/* --- promocje z gazetek: przy pozycji cena i sieć (dotknięcie otwiera arkusz ofert), nad listą pasek sieci z liczbą
   pozycji w promocji (dotknięcie zawęża listę do tej sieci), w menu wybór sieci i ręczne pobranie. */
let offChain=null;
const kr=v=>Number.isInteger(v)?v+',–':v.toFixed(2).replace('.',',');
const chName=id=>(((S.offers||{}).chains||[]).find(c=>c.id===id)||{name:id}).name;
function offPrice(o){   // „34,90”, „2 for 110”, „3 for 2”, „−40 %”
  if(o.percent)return '−'+o.percent+' %';
  const f=(n,p)=>t('offFor').replace('{n}',n).replace('{p}',p);
  if(o.price==null)return o.multi&&o.pay?f(o.multi,o.pay):'?';
  return o.multi>1?f(o.multi,kr(o.price).replace(',–','')):kr(o.price)}
function offBtn(i){const all=i.offers||[];if(!all.length||i.checked)return '';
  const o=(offChain&&all.find(x=>x.chain===offChain))||all[0],n=new Set(all.map(x=>x.chain)).size-1;
  return `<button type="button" class="pr" data-click="openOffers" data-k="${esc(i.key)}" aria-label="${esc(t('offShow'))}"><b>${esc(offPrice(o))}</b><small>${esc(chName(o.chain))}${n>0?' +'+n:''}${o.q?' ?':''}</small></button>`}
function offBar(all){const cs=((S.offers||{}).chains||[]).filter(c=>c.on);if(!cs.length){offChain=null;return ''}
  const list=cs.map(c=>({...c,cnt:all.filter(i=>!i.checked&&(i.offers||[]).some(o=>o.chain===c.id)).length})).sort((a,b)=>b.cnt-a.cnt);
  if(offChain&&!list.some(c=>c.id===offChain&&c.cnt))offChain=null;
  return `<div class="tchips obar"><span class="desc">${t('offBar')}</span>${list.map(c=>`<button class="chip ${offChain===c.id?'on':''}" data-click="offFilter" data-c="${c.id}" aria-pressed="${offChain===c.id}" ${c.cnt?'':'disabled'}>${esc(c.name)} <small>${c.cnt}</small></button>`).join('')}${S.offers.busy?`<span class="desc">${ic('wait')} ${t('offBusy')}</span>`:''}</div>`}
function offFilter(c){offChain=offChain===c?null:c;render();window.scrollTo(0,0)}
function offersSheet(){const i=shopItem(sheet.k);
  return sheetHead(esc(i.extra_id?i.name:nm(i.name)))+`<div class="desc">${t('offHint')}</div>`+i.offers.map(o=>{
    const bundle=o.names.length>1||(o.names[0]&&o.names[0]!==o.title);
    const cond=[o.price!=null&&o.multi>1?`${kr(o.price/o.multi)} ${t('offEach')}`:'',o.member?t('offMember'):'',o.pant?t('offPant'):'',
      o.unit?`${kr(o.unit[1]).replace(',–',',00')}/${o.unit[0]}`:'',t('offTo').replace('{d}',dm(o.to))+(o.assumed?' *':'')].filter(Boolean).join(' · ');
    return `<div class="of"><b>${esc(chName(o.chain))}</b><b class="p">${esc(offPrice(o))}</b>
     <div class="od"><span>${esc(o.title)}${o.q?` <span class="tag">${t('offCheck')}</span>`:''}${bundle?`<br>${esc(o.names.join(', '))}${o.more?' +'+o.more:''}`:''}<br>${esc(cond)}</span>
     <button class="lnk" data-click="offNot" data-k="${esc(i.key)}" data-id="${o.id}">${t('offNot')}</button></div></div>`}).join('')
   +(i.offers.some(o=>o.assumed)?`<p class="desc">* ${t('offAssumed')}</p>`:'')}
async function offNot(k,id){const r=await api('/api/offers/verdict','POST',W({key:k,offer:id,ok:false}));if(!r)return;set(r);
  toast(t('offNotT'),{label:t('undo'),fn:async()=>set(await api('/api/offers/verdict','POST',W({key:k,offer:id,ok:true})))})}
async function offChainSet(c,on){set(await api('/api/offers/chain','POST',W({chain:c,on})))}
async function offPost(){const v=($('#kpc')||{}).value||'';if(!/^\d{4}$/.test(v.trim())){toast(t('offPostBad'));return}
  const r=await api('/api/offers/postcode','POST',W({code:v.trim()}));if(r){set(r);toast(t('offPostOk'))}}
async function offRefresh(){const r=await api('/api/offers/refresh','POST',W({}));if(r){set(r);toast(t('offLoading'))}}
function offMenu(){const o=S.offers;if(!o)return '';
  const st=c=>c.busy?t('offLoading'):!c.on?'':c.postcode===''?t('offNeedPost'):c.at&&c.n?t('offAt').replace('{d}',dm(c.at.slice(0,10))).replace('{n}',c.n)+(c.error?' · '+t('offErrOld'):''):c.error?t('offErr'):t('offNever');
  return `<div class="msec"><b>${ic('shop')} ${t('offT')}</b> <span class="desc">${t('offSub')}</span>
  ${o.chains.map(c=>`<div class="mrow"><span>${esc(c.name)}${st(c)?`<br><span class="desc">${esc(st(c))}</span>`:''}</span><button class="chip ${c.on?'on':''}" data-click="offChainSet" data-c="${c.id}" data-on="${c.on?0:1}" aria-pressed="${c.on}" aria-label="${esc(c.name)}">${c.on?t('offOn'):t('offOff')}</button></div>${c.on&&c.postcode!==undefined?`<div class="inrow"><input id="kpc" inputmode="numeric" maxlength="4" autocomplete="postal-code" placeholder="${esc(t('offPostPh'))}" aria-label="${esc(t('offPostPh'))}" value="${esc(c.postcode)}" data-enter="offPost"><button class="b" data-click="offPost">${t('save')}</button></div>`:''}`).join('')}
  <div class="row"><button class="b" data-click="offRefresh" ${o.chains.some(c=>c.on)&&!o.busy?'':'disabled'}>${t('offUpd')}</button></div></div>`}
/* --- zakupy: pasek postępu, w działach tylko to, co zostało do kupienia (z licznikiem), odhaczone zjeżdżają do zwiniętej
   sekcji „Kupione” na dole, pole dopisywania przy dolnej krawędzi. */
function shop(){
  if(!S.week)return '';
  const g=S.shopping||{},all=Object.values(g).flat(),done=all.filter(i=>i.checked),of=(a,b)=>t('ofN').replace('{a}',a).replace('{b}',b);
  let h='<div class="shop">';
  if(all.length)h+=`<div class="shead"><b>${of(done.length,all.length)}</b><span class="desc">${t('leftN').replace('{n}',all.length-done.length)}</span><span class="sp"></span><button class="b" data-click="copyList">${ic('copy')} ${t('copyS')}</button></div>
   <div class="pbar" role="progressbar" aria-valuemin="0" aria-valuemax="${all.length}" aria-valuenow="${done.length}"><i style="width:${Math.round(100*done.length/all.length)}%"></i></div>`;
  h+=offBar(all);const onOffer=i=>!offChain||(i.offers||[]).some(o=>o.chain===offChain);
  if(S.pending)h+=`<div class="warn">${t('shopWait')}</div>`;
  if(!all.length&&!S.pending)h+=`<div class="card">${t('empty')}</div>`;
  if(all.length&&done.length===all.length)h+=`<div class="card">✓ ${t('allBought')}</div>`;
  for(const [a,items] of Object.entries(g)){const todo=items.filter(i=>!i.checked&&onOffer(i));if(!todo.length)continue;
    h+=`<h3><span>${esc(t(a))}</span><span class="cnt">${of(items.length-todo.length,items.length)}</span></h3>`+todo.map(shopRow).join('')}
  if((S.gone||[]).length)h+=`<h3 style="color:var(--orange)">${t('goneT')}</h3>`+S.gone.map(g=>`<div class="mrow"><span>✓ ${esc(g.label)}</span><button class="b" data-click="dismissG" data-k="${esc(g.key)}">${t('dismiss')}</button></div>`).join('');
  if(done.length&&!offChain)h+=`<button type="button" class="bhead" data-click="foldSec" data-k="bought" aria-expanded="${!!sec.bought}"><span>${t('bought')} (${done.length})</span><span>${ic(sec.bought?'chd':'chr')}</span></button>`+(sec.bought?`<div class="bought">${done.map(shopRow).join('')}</div>`:'');
  if(S.have.length&&!offChain)h+=`<h3>${t('have')}</h3>`+S.have.map(i=>`<div class="haverow"><div class="li">${esc(i.qty)} ${esc(i.unit)} ${esc(nm(i.name))}${usesHtml(i,'have:'+i.key)}</div>${usesBtn(i,'have:'+i.key)}</div>`).join('');
  return h+`<div class="addbar"><input id="xn" placeholder="${esc(t('addPh'))}" data-enter="addX"><button class="b p" data-click="addX" aria-label="${esc(t('add'))}">+</button></div></div>`}
/* --- zakładka Przepisy: książka z wyszukiwaniem, podgląd przepisu, „Wstaw na dzień”, własny przepis */
let bookQ='';
function bookPicked(){return new Map(S.cravings.filter(c=>!c.used&&c.recipe_id).map(c=>[c.recipe_id,c.id]))}
function bookList(){const rs=S.recipes||[],q=bookQ.trim().toLowerCase(),picked=bookPicked();
  if(!rs.length)return `<div class="card">${t('bookEmpty')}</div>`;
  const list=rs.filter(r=>{if(!q)return true;const v=rv(r);return [v.name,v.description,r.name,...v.ing,...r.ingredients.map(i=>i.name)].join(' ').toLowerCase().includes(q)});
  if(!list.length)return `<div class="card">${t('bookNone')}</div>`;
  return list.map(r=>{const v=rv(r),on=picked.has(r.id);return `<div class="brow" data-rid="${r.id}"><button class="nmb" data-click="openBook" data-id="${r.id}"><span class="name">${esc(v.name)}</span><span class="desc">${esc([r.time_min?r.time_min+' min':'',v.description].filter(Boolean).join(' · '))}</span></button>
   <button class="chip ${on?'on':''}" data-click="togglePick" data-id="${r.id}" aria-pressed="${on}">${on?'✓ '+t('inPlan'):ic('plus')+' '+t('toPlan')}</button></div>`}).join('')}
function book(){return `<div class="book"><div class="inrow"><input id="bq" placeholder="${esc(t('bookSearch'))}" value="${esc(bookQ)}" data-input="bookQ" autocomplete="off"><button class="b" data-click="toggleCust">${ic('plus')} ${t('custBtn')}</button></div>
  ${custOpen?custPanel():''}<div class="desc bhint">${t('bookHint')}</div><div id="blist">${bookList()}</div></div>`}
// Podgląd przepisu z książki. „Wstaw na dzień” ma dwa kroki: wybór dnia pokazuje, jakie danie zostanie zastąpione, dopiero „Wstaw tutaj” zapisuje.
function bookSheet(r){const v=rv(r),on=bookPicked().has(r.id),D=t('days');let use='';
  if(S.week){const k=sheet.day,m=k!=null?S.meals.find(x=>x.day===k):null;
    use=`<div class="lbl">${t('useT')} · ${t('wk')}${isoWk(S.week.start)}</div><div class="chips">${t('daysS').map((x,i)=>`<button class="chip ${i===k?'on':''}" data-click="useDay" data-d="${i}" aria-label="${esc(D[i])}" aria-pressed="${i===k}">${esc(x)}</button>`).join('')}</div>`
     +(m?`<div class="alt"><b>${esc(D[k])} ${dm(m.date)}</b><div class="desc">${m.status==='removed'?t('dayOffS'):esc(t('useNow').replace('{x}',mv(m).name))}</div>
      <div class="row"><button class="b p" data-click="useRec" data-id="${r.id}" data-d="${k}">${t('useGo')}</button></div></div>`:'')}
  return `${sheetHead(esc(v.name))}<div class="desc">${esc([v.description,r.time_min?r.time_min+' min':''].filter(Boolean).join(' · '))}</div>
   ${v.steps.length?`<div class="row"><button class="b p" data-click="openCook" data-rid="${r.id}">${ic('pot')} ${t('cookBtn')}</button></div>`:''}
   ${use}<button class="act" data-click="togglePick" data-id="${r.id}" aria-pressed="${on}">${on?'✓ '+t('inPlan'):ic('plus')+' '+t('toPlan')}</button>
   <h3>${t('sectIng')}</h3><ul class="ings">${r.ingredients.map((i,k)=>`<li>${esc(i.qty??'')} ${esc(i.unit)} ${esc(v.ing[k]||i.name)}</li>`).join('')}</ul>
   <h3>${t('sectStp')}</h3><ol class="steps">${v.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol>
   ${okUrl(r.source)?`<a class="lnk" href="${esc(r.source)}" target="_blank" rel="noopener">${t('src')} ↗</a>`:''}
   <button class="act danger" data-click="delRecAsk" data-id="${r.id}">${ic('del')} ${t('delRecL')}</button>`}
function delRecAsk(id){const r=(S.recipes||[]).find(x=>x.id===id);if(!r)return;
  sheet=null;openSheet({kind:'confirm',title:rv(r).name,text:t('delRecQ'),yes:t('del'),fn:()=>delRec(id)})}
function rv(r){const x=lang!=='no'&&r.tr&&r.tr[lang];return x?{name:x.name,description:x.description,ing:x.ingredients,steps:x.steps}:{name:r.name,description:r.description,ing:r.ingredients.map(i=>i.name),steps:r.steps}}
let wizDraft=null,wizBusy=false;
function latestWeek(){return (S.weeks||[]).reduce((a,w)=>!a||w.start>a.start?w:a,null)}
let wizT=null;
// force: pobierz szkic jeszcze raz (ceny dań dochodzą w tle, więc karta szkicu odświeża się, dopóki coś jest „w toku”)
async function wizSync(force){const lw=latestWeek();
  if(!lw||lw.confirmed){if(wizDraft){wizDraft=null}return}
  if((!force&&wizDraft&&wizDraft.id===lw.id)||wizBusy)return;
  wizBusy=true;
  try{const r=await fetch('/api/state?week='+lw.id);if(r.ok){const d=await r.json();
    wizDraft={id:lw.id,start:lw.start,end:lw.end,prices:d.prices,meals:d.meals.map(m=>({id:m.id,day:m.day,name:m.name,tr:m.tr,kid:!!m.kid}))};
    if(tab==='fridge'&&!drag)render()}}catch(e){}
  wizBusy=false;clearTimeout(wizT);
  if(wizDraft&&((wizDraft.prices&&wizDraft.prices.pending)||(kOn()&&wizDraft.meals.some(m=>!m.kid)))&&tab==='fridge')wizT=setTimeout(()=>{if(tab==='fridge')wizSync(true)},4000)}
/* --- ceny orientacyjne (Kassalapp): tylko w szkicu planu. P = S.prices szkicu albo null (brak klucza, ceny wyłączone). */
const krP=x=>(+x).toFixed(2).replace('.',',');
function priceCell(P,id){const x=P&&P.meals[id];if(!x)return '';
  if(x.pending)return `<span class="pr mu">${t('prWait')}</span>`;
  if(x.few)return `<span class="pr mu">${t('prFew')}</span>`;
  return `<span class="pr">≈ ${x.kr} kr</span>`}
function priceSum(P){if(!P||!P.total)return '';
  const miss=Object.values(P.meals).reduce((a,x)=>a+(x.missing||0),0);
  return `<div class="wsum"><i>${t('prWeek')}</i><b>${P.counted?'≈ '+P.kr+' kr':'…'}</b></div>
   <div class="desc wsub">${[t('prCnt').replace('{a}',P.counted).replace('{b}',P.total),P.pp?t('prPP').replace('{n}',P.pp):'',miss?t('prMiss').replace('{n}',miss):'',t('prApprox')].filter(Boolean).join(' · ')}</div>`}
function priceMenu(){const p=S.price_cfg;if(!p)return '';
  if(!p.key)return `<div class="mrow"><span>${t('prT')}<div class="desc">${t('prNoKey')}</div></span></div>`;
  return `<div class="mrow"><span>${t('prT')}<div class="desc">${t('prHint')}</div></span><span class="seg"><button class="${p.on?'on':''}" data-click="priceOn" data-on="1">${t('prOn')}</button><button class="${p.on?'':'on'}" data-click="priceOn" data-on="">${t('prOff')}</button></span></div>`
   +(p.on?`<div class="mrow"><span>${t('prMapT')}<div class="desc">${t('prMapN').replace('{a}',p.mapped).replace('{b}',p.total)}${p.check?' · '+t('prChk').replace('{n}',p.check):''}${p.refreshed?' · '+dm(p.refreshed):''}</div></span><button class="b" data-click="priceMap">${t('open')}</button></div>`:'')}
let pmap=null;
async function priceOn(on){set(await api('/api/prices/on','POST',{on:!!on}));wizSync(true)}
async function priceMap(){try{const r=await fetch('/api/prices/map');pmap=(await r.json()).items}catch(e){pmap=[]}
  sheet={kind:'pmap'};render()}
function packTxt(x){return x.pack?(x.fam==='g'&&x.pack>=1000?(x.pack/1000)+' kg':x.fam==='ml'&&x.pack>=1000?(x.pack/1000)+' l':x.pack+' '+x.fam):''}
function prodLine(x){return [krP(x.price)+' kr',packTxt(x),x.chain,x.pdate?dm(x.pdate):''].filter(Boolean).map(esc).join(' · ')}
function pmapSheet(){const st={none:t('prNone'),auto:t('prAuto'),off:t('prSkip')};
  return `${sheetHead(t('prMapT'))}<div class="desc">${t('prMapHint')}</div>`+((pmap||[]).length?pmap.map(x=>
   `<button class="act" data-click="priceItem" data-k="${esc(x.canon)}"><span class="li"><b>${esc(nm(x.label))}</b><div class="desc">${x.ean&&x.source!=='off'?esc(x.name)+' · '+krP(x.price)+' kr':'–'}</div></span>${st[x.source]?`<span class="tag">${st[x.source]}</span>`:''}</button>`).join('')
   :`<p class="ptxt">${t('prMapNone')}</p>`)}
function pitemSheet(){const x=(pmap||[]).find(i=>i.canon===sheet.k);if(!x)return pmapSheet();
  return `${sheetHead(esc(nm(x.label))+': '+t('prWhich'))}<div class="desc">${t('prRemember')}</div>`
   +(x.cands.length?x.cands.map(c=>{const on=x.source!=='off'&&c.ean===x.ean;
     return `<button class="act pick" data-click="pricePick" data-k="${esc(x.canon)}" data-e="${esc(c.ean)}" aria-pressed="${on}"><i class="rb ${on?'on':''}"></i><span class="li">${esc(c.name)}<div class="desc">${prodLine(c)}</div></span></button>`}).join('')
    :`<p class="ptxt">${t('prNoCand')}</p>`)
   +`<div class="inrow"><input id="pq" placeholder="${esc(t('prSearchPh'))}" data-enter="priceSearch" data-k="${esc(x.canon)}"><button class="b" data-click="priceSearch" data-k="${esc(x.canon)}">${t('search')}</button></div>
   <div class="row"><button class="b" data-click="priceMap">${ic('chl')} ${t('back')}</button><span class="sp"></span><button class="b" data-click="priceSkip" data-k="${esc(x.canon)}" aria-pressed="${x.source==='off'}">${t('prSkipBtn')}${x.source==='off'?' ✓':''}</button></div>`}
async function priceSave(body,path){const r=await api(path||'/api/prices/map','POST',body);if(r&&r.items){pmap=r.items;render();refreshQuiet();wizSync(true)}}
function pricePick(k,e){priceSave({canon:k,ean:e})}
function priceSkip(k){priceSave({canon:k,off:true})}
function priceSearch(k){const q=($('#pq')||{}).value||'';if(q.trim().length<2)return;priceSave({canon:k,q:q.trim()},'/api/prices/search')}
function shouldOpenWizard(s){if(!s)return false;
  const future=(s.weeks||[]).some(w=>w.start>s.today);
  const days=Math.round((new Date(s.next_start+'T12:00:00')-new Date((s.today||s.next_start)+'T12:00:00'))/864e5);
  return !future&&days<=2}
function goTab(k){tab=k;if(k==='fridge'&&wizDraft)wizSync(true);render();window.scrollTo(0,0)}
function fridge(){
  const D=t('days');
  const lw=latestWeek();const draft=lw&&!lw.confirmed?wizDraft:null;
  const target=draft?{start:draft.start,end:draft.end}:{start:S.next_start,end:(()=>{const d=new Date(S.next_start+'T12:00:00');d.setDate(d.getDate()+6);return d.toISOString().slice(0,10)})()};
  const free=S.cravings.filter(c=>!c.used);
  const picked=new Map(free.filter(c=>c.recipe_id).map(c=>[c.recipe_id,c.id]));
  const jobRunning=!!jobId;
  let h=`<div class="card" style="background:var(--wiz)"><b style="font-size:17px">${ic('week')} ${t('wizHead')} ${t('wk')}${isoWk(target.start)} · ${dm(target.start)}–${dm(target.end)}</b>
   <div class="desc" style="margin-top:4px">${t('wizSub')}</div></div>`;
  if(lw&&!lw.confirmed){
    h+=`<div class="card" style="border:2px solid var(--ac)"><b>${t('draftT')} · ${t('wk')}${isoWk(lw.start)}</b>
    ${draft?draft.meals.map(m=>{const x=lang!=='no'&&m.tr&&m.tr[lang];return `<div class="desc drow" style="padding:3px 0;border-bottom:1px solid var(--line)"><span><b>${D[m.day]}</b> · ${esc(x?x.name:m.name)}</span>${priceCell(draft.prices,m.id)}</div>`}).join('')+priceSum(draft.prices)+(kOn()?`<div class="desc" style="padding-top:6px">${esc(t('kidDraft').replace('{n}',S.kid.name).replace('{a}',draft.meals.filter(m=>m.kid).length).replace('{b}',draft.meals.length))}</div>`:''):`<div class="desc">…</div>`}
    <div class="row"><button class="b p" data-click="confirmWeek" data-id="${lw.id}">${t('confirmBtn')}</button><button class="b" data-click="goWeek" data-id="${lw.id===S.current_id?'':lw.id}">${t('openPlan')}</button><button class="b" style="color:var(--bad);border-color:var(--badbd)" data-click="delWeek" data-id="${lw.id}" aria-label="${esc(t('delWeek'))}">${ic('del')}</button></div></div>`;
  }else if(lw&&lw.start>S.today){
    h+=`<div class="warn" style="background:var(--ok);border-color:var(--okbd)"><b>${t('wk')}${isoWk(lw.start)} · ${dm(lw.start)} ${t('nextReady')}</b><div class="desc">${t('nextAfter')} ${t('wk')}${isoWk(S.next_start)} · ${dm(S.next_start)}</div>
    <div class="row"><button class="b" data-click="goWeek" data-id="${lw.id}">${t('openPlan')}</button></div></div>`;
  }
  h+=`<div class="card">${secHead('pantry',ic('snow'),t('fTitle'),S.pantry.length,S.pantry.map(p=>p.name).join(', '))}${sec.pantry?`<div class="secbody"><div class="desc" style="font-size:12px;margin-top:2px">${t('pantryHint')}</div>
   <div class="row"><input id="pn" placeholder="${esc(t('fPh'))}" data-enter="addP" style="flex:1"><button class="b p" data-click="addP">${t('add')}</button></div>
   <ul style="list-style:none;padding:0">${S.pantry.map(p=>`<li class="mrow"><span>${esc(p.name)}</span><button type="button" class="mb" data-click="delP" data-id="${p.id}" aria-label="${esc(t('del'))}">${ic('x')}</button></li>`).join('')}</ul></div>`:''}</div>
  <div class="card">${secHead('crav',ic('heart'),t('cTitle'),free.filter(c=>!c.recipe_id).length+picked.size,[...free.filter(c=>!c.recipe_id).map(c=>c.text),...(S.recipes||[]).filter(r=>picked.has(r.id)).map(r=>rv(r).name)].join(', '))}${sec.crav?`<div class="secbody"><div class="desc" style="font-size:12px;margin-top:2px">${t('linkHint')}</div>
   <div class="row"><input id="cn" placeholder="${esc(t('cPh'))}" data-enter="addC" style="flex:1"><button class="b p" data-click="addC">${t('add')}</button></div>
   <ul style="list-style:none;padding:0">${free.filter(c=>!c.recipe_id).map(c=>`<li class="mrow"><span>${esc(c.text)}</span><button type="button" class="mb" data-click="delC" data-id="${c.id}" aria-label="${esc(t('del'))}">${ic('x')}</button></li>`).join('')}</ul></div>`:''}</div>
  <div class="card"><div class="mrow" style="border:0"><span><b>${ic('fav')} ${t('book')}</b> <span class="cnt">${(S.recipes||[]).length}</span><div class="desc">${t('bookPickHint')}</div></span><button class="b" data-click="goTab" data-t="book">${t('open')} →</button></div>
   ${(S.recipes||[]).filter(r=>picked.has(r.id)).map(r=>`<div class="mrow"><span>✓ ${esc(rv(r).name)}</span><button type="button" class="mb" data-click="togglePick" data-id="${r.id}" aria-label="${esc(t('del'))}">${ic('x')}</button></div>`).join('')}</div>
  ${draft?'':`<div class="row"><button class="b p" style="flex:1;padding:14px;font-size:16px" ${jobRunning?'disabled':''} data-click="gen">${ic('plan')} ${t('goBtn')}</button></div>`}`;
  return h}
// Usunięcie całego tygodnia: jedyna akcja z potwierdzeniem (nie da się jej cofnąć), ale we własnym arkuszu, nie w oknie systemowym.
function delWeek(wid){const w=(S.weeks||[]).find(x=>x.id===wid);
  sheet=null;openSheet({kind:'confirm',title:w?`${t('week')} ${isoWk(w.start)} · ${dm(w.start)}`:t('delWeek'),text:t('delWeekQ'),yes:t('delWeekYes'),fn:()=>doDelWeek(wid)})}
async function doDelWeek(wid){wizDraft=null;viewWeek=null;
  const r=await api('/api/week/'+wid,'DELETE');if(r){adopt(r);render();ensureTr()}}
async function confirmWeek(wid){wizDraft=null;const r=await api('/api/week/confirm','POST',{week:wid},t('jFill'));
  if(r){const jid=r.job;viewWeek=wid===r.current_id?null:wid;set(r);goTab('plan');if(jid){jobId=jid;clearTimeout(jobTimer);pollJob()}kidAfterConfirm()}}
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
  $('#jb_t').textContent=((!fill&&j.stage==='plan')?t('jPlan'):t(fill?'jFill':'jRec')+' '+done+'/'+total);
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
  if(sheet)sheet.why=false;set(r);toast(t('dislikeDone'));$('#panel').scrollTop=0}
async function dislikeOff(id){const r=await api(`/api/meal/${id}/dislike`,'POST',{reason:''});if(r){set(r);toast(t('dislikeOff'))}}
async function undislike(did){set(await api(`/api/dislikes/${did}`+(viewWeek?`?week=${viewWeek}`:''),'DELETE'))}
async function fav(id){const r=await api(`/api/meal/${id}/favorite`);if(r){const m=r.meals.find(x=>x.id===id);set(r);if(m&&m.fav)toast(t('favOn'))}}
async function carry(id){set(await api(`/api/meal/${id}/carry`))}
function toggleAIng(k){openAIng[k]=!openAIng[k];render()}
async function confirmPlan(){const r=await api('/api/week/confirm','POST',W({}),t('jFill'));if(r){const jid=r.job;set(r);if(jid){jobId=jid;clearTimeout(jobTimer);pollJob()}kidAfterConfirm()}}
async function balFix(id){const r=await api(`/api/meal/${id}/balance`,'POST',undefined,t('balFixing'));if(r){set(r);toast(t('balFixed'))}}
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
  const r=added('#cn',raw,await api('/api/cravings','POST',{text:v},isU?t('bImport'):undefined));if(r){set(r);if(isU)toast(t('favOn'))}}
async function delC(id){set(await api('/api/cravings/'+id,'DELETE'))}
async function delRec(id){set(await api('/api/recipes/'+id,'DELETE'))}
async function useRec(id,d){const rc=(S.recipes||[]).find(x=>x.id===id);closeSheet();
  const r=await api(`/api/recipes/${id}/use`,'POST',W({day:d}));if(r){set(r);tab='plan';render();window.scrollTo(0,0);toast('✓ '+t('usedT')+(rc?rv(rc).name:''))}}
async function addX(){const v=$('#xn').value;if(!v.trim())return;set(added('#xn',v,await api('/api/shop/extra','POST',W({name:v}))))}
const AISLES=['Moje produkty','Frukt og grønt','Tørrvarer og hermetikk','Krydder og basis','Brød og deig','Kjøtt og fisk','Frys','Meieri og kjøl','Snacks og godteri'];
function extraItem(id){for(const [a,g] of Object.entries((S&&S.shopping)||{})){const i=g.find(x=>x.extra_id===id);if(i)return {...i,aisle:a}}return null}
async function setAisle(id,a){set(await api(`/api/shop/extra/${id}/aisle`,'POST',{aisle:a}))}
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
/* --- zakładka Zadania: wspólne listy rzeczy do zrobienia. Listy przełącza się u góry; w liście kolejność jest priorytetem
   (przeciąganie za uchwyt z numerem albo strzałki w arkuszu pozycji). Pozycja może mieć kroki: wiersz pokazuje wtedy pasek,
   następny krok i licznik, a po odhaczeniu ostatniego kroku cała pozycja przechodzi do zrobionych.
   Endpointy /api/todo/* zwracają samo {todo}, bez przeliczania tygodnia i zakupów. */
let todoSel=+localStorage.getItem('todoList')||null,flashT=null,tdrag=null;
const todoFlash=new Set(),todoDots=new Set();   // pozycje i listy zmienione na drugim telefonie: podświetlenie na chwilę, kropka do otwarcia listy
const tLists=()=>(S&&S.todo&&S.todo.lists)||[];
const tOpen=l=>l.items.filter(i=>!i.done);
const ofN=(a,b)=>t('ofN').replace('{a}',a).replace('{b}',b);
function tCur(){const ls=tLists();return ls.find(l=>l.id===todoSel)||ls[0]||null}
function tFind(id){for(const l of tLists()){const i=l.items.find(x=>x.id===id);if(i)return {l,i}}return null}
function tSel(id){todoSel=id;localStorage.setItem('todoList',id);todoDots.delete(id)}
function tPick(id){tSel(id);render();window.scrollTo(0,0)}
function setTodo(r){if(!r||!r.todo)return;
  if(pending)return;   // jak w set(): ekran odświeży odpowiedź ostatniej akcji z kolejki
  S.todo=r.todo;render()}
function tMark(ids){ids.forEach(i=>todoFlash.add(i));clearTimeout(flashT);
  flashT=setTimeout(()=>{todoFlash.clear();if(S&&!tdrag)render()},6000)}
// Porównanie stanu z tła z tym na ekranie: co druga osoba dodała albo zmieniła.
function todoDiff(a,b){if(!a||!b)return;const old=new Map(),cur=tCur(),ch=[];
  a.lists.forEach(l=>l.items.forEach(i=>old.set(i.id,JSON.stringify([l.id,i]))));
  b.lists.forEach(l=>{let any=false;l.items.forEach(i=>{if(old.get(i.id)!==JSON.stringify([l.id,i])){any=true;if(!i.done)ch.push(i.id)}});
    if(any&&cur&&l.id!==cur.id)todoDots.add(l.id)});
  if(ch.length)tMark(ch)}
function tRow(i,n){const st=i.steps,dn=st.filter(s=>s.done).length,nx=st.find(s=>!s.done),prog=st.length&&!i.done;
  const sub=[i.due&&!i.done?`<span class="${i.due<S.todo.today?'late':''}">${esc(t('tDueBy').replace('{d}',dm(i.due)))}</span>`:'',prog&&nx?esc(t('tNext').replace('{x}',nx.name)):''].filter(Boolean).join(' · ');
  return `<div class="trow${i.done?' done':''}${todoFlash.has(i.id)?' new':''}" data-id="${i.id}">${i.done?'':`<span class="tgrip"><small>⋮⋮</small><b>${n}</b></span>`}
   <button class="nmb" data-click="openT" data-id="${i.id}"><span class="name">${esc(i.name)}</span>${prog?`<span class="pbar"><i style="width:${Math.round(100*dn/st.length)}%"></i></span>`:''}${sub?`<span class="desc">${sub}</span>`:''}</button>
   ${prog?`<button class="tcnt" data-click="openT" data-id="${i.id}" aria-label="${esc(t('tSteps')+' '+ofN(dn,st.length))}">${dn}/${st.length}</button>`
     :`<button class="ck${i.done?' on':''}" data-click="tDone" data-id="${i.id}" data-on="${i.done?0:1}" aria-pressed="${!!i.done}" aria-label="${esc(t('tMark')+': '+i.name)}"></button>`}</div>`}
function todo(){const ls=tLists(),cur=tCur();
  if(!cur)return `<div class="card"><b>${t('tFirstT')}</b><p class="ptxt">${t('tFirst')}</p>
   <div class="chips">${t('tSug').map(n=>`<button class="chip" data-click="tNewList" data-n="${esc(n)}">${esc(n)}</button>`).join('')}</div>
   <div class="inrow"><input id="tln" placeholder="${esc(t('tListPh'))}" data-enter="tNewList"><button class="b p" data-click="tNewList">${t('tCreate')}</button></div></div>`;
  const open=tOpen(cur),done=cur.items.filter(i=>i.done);
  let h=`<div class="todo"><div class="tchips">${ls.map(l=>{const n=tOpen(l).length;return `<button class="chip${l.id===cur.id?' on':''}${todoDots.has(l.id)?' dot':''}" data-click="tPick" data-id="${l.id}" aria-pressed="${l.id===cur.id}">${esc(l.name)}${n?` <small>${n}</small>`:''}</button>`}).join('')}<button class="chip" data-click="tListNew" aria-label="${esc(t('tNewList'))}">+</button></div>
   <div class="shead"><span class="desc">${t('leftN').replace('{n}',open.length)}</span><span class="sp"></span><button class="mb" data-click="tListMenu" data-id="${cur.id}" aria-label="${esc(t('tListOpts'))}">⋯</button></div>`;
  if(!cur.items.length)h+=`<div class="card">${t('tEmpty')}</div>`;
  else if(!open.length)h+=`<div class="card">✓ ${t('tAllDone')}</div>`;
  h+=`<div class="trows">${open.map((i,n)=>tRow(i,n+1)).join('')}</div>`;
  if(done.length)h+=`<button type="button" class="bhead" data-click="foldSec" data-k="tdone" aria-expanded="${!!sec.tdone}"><span>${t('tDoneT')} (${done.length})</span><span>${sec.tdone?'▾':'▸'}</span></button>`+(sec.tdone?`<div class="trows" style="margin-top:8px">${done.map(i=>tRow(i,0)).join('')}</div>`:'');
  return h+`<div class="addbar"><input id="tn" placeholder="${esc(t('tAddPh'))}" data-enter="addT"><button class="b p" data-click="addT" aria-label="${esc(t('add'))}">+</button></div></div>`}
// Arkusz pozycji: kolejność, kroki, termin, przeniesienie do innej listy, nazwa, usunięcie.
function tItemSheet(){const {l,i}=tFind(sheet.id),id=i.id,open=tOpen(l),ix=open.indexOf(i),st=i.steps,others=tLists().filter(x=>x.id!==l.id);
  let h=sheetHead(esc(i.name));
  if(sheet.edit)h+=`<div class="inrow"><input id="trn" value="${esc(i.name)}" data-enter="tRenameSave" data-id="${id}"><button class="b p" data-click="tRenameSave" data-id="${id}">${t('save')}</button></div>`;
  if(!i.done)h+=`<div class="mrow"><span>${t('tOrder')}</span><span class="stp"><button class="b" data-click="tMove" data-id="${id}" data-i="${ix-1}" ${ix<=0?'disabled':''} aria-label="${esc(t('tUp'))}">↑</button><b>${ofN(ix+1,open.length)}</b><button class="b" data-click="tMove" data-id="${id}" data-i="${ix+1}" ${ix>=open.length-1?'disabled':''} aria-label="${esc(t('tDown'))}">↓</button></span></div>
   ${ix>0?`<button class="act" data-click="tMove" data-id="${id}" data-i="0">⤒ ${t('tToTop')}</button>`:''}`;
  h+=`<div class="lbl">${t('tSteps')}${st.length?' · '+ofN(st.filter(s=>s.done).length,st.length):''}</div>`
   +st.map(s=>`<div class="tstep${s.done?' c':''}"><button class="ck${s.done?' on':''}" data-click="tStep" data-id="${s.id}" data-on="${s.done?0:1}" aria-pressed="${!!s.done}" aria-label="${esc(s.name)}"></button><span>${esc(s.name)}</span><button class="mb" data-click="tStepDel" data-id="${s.id}" aria-label="${esc(t('del')+': '+s.name)}">✕</button></div>`).join('')
   +`<div class="inrow"><input id="tsn" placeholder="${esc(t('tStepPh'))}" data-enter="tStepAdd" data-id="${id}"><button class="b p" data-click="tStepAdd" data-id="${id}" aria-label="${esc(t('tStepPh'))}">+</button></div>
   <div class="mrow" style="margin-top:8px"><span>📅 ${t('tDue')}</span><span class="tdue"><input type="date" id="tdue" aria-label="${esc(t('tDue'))}" value="${esc(i.due||'')}" data-change="tDue" data-id="${id}">${i.due?`<button class="b" data-click="tDueClear" data-id="${id}" aria-label="${esc(t('tNoDue'))}">✕</button>`:''}</span></div>`;
  if(others.length)h+=`<div class="lbl">${t('tMoveTo')}</div><div class="chips">${others.map(x=>`<button class="chip" data-click="tToList" data-id="${id}" data-l="${x.id}">${esc(x.name)}</button>`).join('')}</div>`;
  if(i.done)h+=`<button class="act" data-click="tDone" data-id="${id}" data-on="0">↩ ${t('restore')}</button>`;
  if(!sheet.edit)h+=`<button class="act" data-click="tRename">✎ ${t('tRename')}</button>`;
  return h+`<button class="act danger" data-click="tDelAsk" data-id="${id}">${t('del')}</button>`}
// Arkusz listy: bez id nowa lista (z podpowiedziami nazw), z id zmiana nazwy i usunięcie.
function tListSheet(){const l=sheet.id&&tLists().find(x=>x.id===sheet.id);
  if(l)return `${sheetHead(esc(l.name))}<div class="inrow"><input id="tle" value="${esc(l.name)}" data-enter="tListSave" data-id="${l.id}"><button class="b p" data-click="tListSave" data-id="${l.id}">${t('save')}</button></div>
   <button class="act danger" style="margin-top:8px" data-click="tListDelAsk" data-id="${l.id}">${t('tDelList')}</button>`;
  const have=new Set(tLists().map(x=>x.name.toLowerCase())),sug=t('tSug').filter(n=>!have.has(n.toLowerCase()));
  return `${sheetHead(t('tNewList'))}<div class="inrow"><input id="tln" placeholder="${esc(t('tListPh'))}" data-enter="tNewList"><button class="b p" data-click="tNewList">${t('tCreate')}</button></div>
   ${sug.length?`<div class="lbl">${t('tSugT')}</div><div class="chips">${sug.map(n=>`<button class="chip" data-click="tNewList" data-n="${esc(n)}">${esc(n)}</button>`).join('')}</div>`:''}`}
async function tNewList(n){const v=(n||($('#tln')||{}).value||'').trim();if(!v)return;
  const r=await api('/api/todo/list','POST',{name:v});if(!r)return;
  const e=$('#tln');if(e)e.value='';if(sheet)closeSheet();tSel(r.list);setTodo(r)}
async function tListSave(id){const v=(($('#tle')||{}).value||'').trim();if(!v)return;closeSheet();setTodo(await api('/api/todo/list/'+id,'POST',{name:v}))}
function tListDelAsk(id){const l=tLists().find(x=>x.id===id);if(!l)return;
  sheet=null;openSheet({kind:'confirm',title:l.name,text:t('tDelListQ').replace('{n}',l.items.length),yes:t('tDelList'),fn:async()=>{todoSel=null;setTodo(await api('/api/todo/list/'+id,'DELETE'))}})}
function openT(id){if(tFind(id))openSheet({kind:'titem',id})}
async function addT(){const cur=tCur(),v=($('#tn')||{}).value||'';if(!cur||!v.trim())return;
  const r=added('#tn',v,await api('/api/todo/item','POST',{list:cur.id,name:v}));if(!r)return;
  tMark([r.item]);setTodo(r);const el=$(`.trow[data-id="${r.item}"]`);if(el)el.scrollIntoView({block:'nearest'});
  const f=tFind(r.item);if(f&&tOpen(f.l).length>1)toast(t('tAdded'),{label:t('tTop'),fn:()=>tMove(r.item,0)})}
async function tMove(id,ix){setTodo(await api(`/api/todo/item/${id}/move`,'POST',{index:ix}))}
// Odhaczenie widać od razu, zapis idzie w tle; po nieudanym zapisie api() przywraca stan z serwera.
async function tDone(id,on){const f=tFind(id);if(!f)return;f.i.done=on;if(sheet&&sheet.kind==='titem')closeSheet();else render();
  setTodo(await api('/api/todo/item/'+id,'POST',{done:on}))}
async function tStep(sid,on){const f=sheet&&tFind(sheet.id),s=f&&f.i.steps.find(x=>x.id===sid);if(!s)return;
  const was=f.i.done;s.done=on;render();
  const r=await api('/api/todo/step/'+sid,'POST',{done:on});if(!r)return;setTodo(r);
  const g=tFind(f.i.id);if(g&&g.i.done&&!was&&sheet&&sheet.kind==='titem'&&sheet.id===g.i.id){closeSheet();toast('✓ '+g.i.name)}}   // ostatni krok: cała pozycja zrobiona
async function tStepDel(sid){setTodo(await api('/api/todo/step/'+sid,'DELETE'))}
async function tStepAdd(id){const v=($('#tsn')||{}).value||'';if(!v.trim())return;
  setTodo(added('#tsn',v,await api(`/api/todo/item/${id}/step`,'POST',{name:v})));const e=$('#tsn');if(e)e.focus()}
async function tDue(id,v){setTodo(await api('/api/todo/item/'+id,'POST',{due:v}))}
async function tToList(id,lid){const l=tLists().find(x=>x.id===lid);closeSheet();
  const r=await api('/api/todo/item/'+id,'POST',{list:lid});if(r){setTodo(r);if(l)toast(t('tMoved').replace('{x}',l.name))}}
function tRename(){sheet.edit=true;render();const e=$('#trn');if(e){e.focus();e.select()}}
async function tRenameSave(id){const v=(($('#trn')||{}).value||'').trim();if(!v)return;sheet.edit=false;setTodo(await api('/api/todo/item/'+id,'POST',{name:v}))}
function tDelAsk(id){const f=tFind(id);if(!f)return;
  sheet=null;openSheet({kind:'confirm',title:f.i.name,text:t('tDelQ'),yes:t('del'),fn:async()=>setTodo(await api('/api/todo/item/'+id,'DELETE'))})}
/* Przeciąganie pozycji w liście: uchwytem jest numer, wiersz jedzie za palcem w pionie, kreska pokazuje miejsce wstawienia.
   Dotknięcie numeru bez ruchu otwiera arkusz pozycji, tak jak dotknięcie nazwy. */
function tdragAt(){const d=tdrag,rows=[...d.box.children].filter(r=>r!==d.row),r0=d.row.getBoundingClientRect(),mid=r0.top+r0.height/2;
  let ix=0;for(const r of rows){const b=r.getBoundingClientRect();if(mid>b.top+b.height/2)ix++}
  rows.forEach((r,n)=>{r.classList.toggle('insb',n===ix);r.classList.toggle('insa',ix===rows.length&&n===rows.length-1)});return ix}
function tdragLoop(){if(!tdrag)return;const d=tdrag;
  if(!d.moved&&Math.abs(d.y-d.y0)>6){d.moved=true;d.row.classList.add('dragging')}
  if(d.moved){d.row.style.transform=`translateY(${(d.y-d.y0)+(window.scrollY-d.s0)}px)`;
    if(d.y<90)window.scrollBy(0,-10);else if(d.y>innerHeight-150)window.scrollBy(0,10);
    d.ix=tdragAt()}
  requestAnimationFrame(tdragLoop)}
document.addEventListener('pointerdown',e=>{const g=e.target.closest&&e.target.closest('.tgrip');if(!g||tdrag||drag)return;
  e.preventDefault();const row=g.closest('.trow');
  tdrag={row,box:row.parentElement,id:+row.dataset.id,y:e.clientY,y0:e.clientY,s0:window.scrollY,moved:false,ix:null};
  try{g.setPointerCapture(e.pointerId)}catch(_){}
  requestAnimationFrame(tdragLoop)});
document.addEventListener('pointermove',e=>{if(tdrag){tdrag.y=e.clientY;e.preventDefault()}},{passive:false});
function tdragEnd(e,cancel){if(!tdrag)return;const d=tdrag;
  if(!cancel){d.y=e.clientY;if(Math.abs(d.y-d.y0)>6){d.moved=true;d.row.style.transform=`translateY(${(d.y-d.y0)+(window.scrollY-d.s0)}px)`;d.ix=tdragAt()}}
  tdrag=null;d.row.classList.remove('dragging');d.row.style.transform='';
  d.box.querySelectorAll('.insb,.insa').forEach(r=>r.classList.remove('insb','insa'));
  if(cancel)return;if(!d.moved){openT(d.id);return}
  const cur=tCur(),open=cur?tOpen(cur):[],from=open.findIndex(i=>i.id===d.id);
  if(d.ix==null||from<0||d.ix===from)return;
  open.splice(d.ix,0,open.splice(from,1)[0]);cur.items=[...open,...cur.items.filter(i=>i.done)];render();   // nowa kolejność od razu na ekranie
  tMove(d.id,d.ix)}
document.addEventListener('pointerup',e=>tdragEnd(e,false));
document.addEventListener('pointercancel',e=>tdragEnd(e,true));
function applyTheme(){const s=localStorage.getItem('theme');const d=s?s==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
  if(d)document.documentElement.setAttribute('data-theme','dark');else document.documentElement.removeAttribute('data-theme');
  const mt=document.querySelector('meta[name=theme-color]');if(mt)mt.content=d?'#151b1e':'#e8ecea'}
function setTheme(th){localStorage.setItem('theme',th);applyTheme();if(S)render()}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(!localStorage.getItem('theme'))applyTheme()});
applyTheme();
document.querySelectorAll('[data-ic]').forEach(e=>{e.innerHTML=ic(e.dataset.ic)});
setLang(lang);load();pollJob();
/* --- współdzielenie: świeży stan co 15 s, gdy strona jest widoczna, i od razu po powrocie --- */
function typing(){const a=document.activeElement;return !!(a&&(a.tagName==='INPUT'||a.tagName==='TEXTAREA'||a.tagName==='SELECT')&&a.type!=='checkbox')}
function busyUI(){return pending||drag||tdrag||typing()||(S&&S.meals&&S.meals.some(m=>m.loading||m.choosing!=null||m.closing))}
async function sync(){if(document.hidden||busyUI()||!S)return;
  const seq=mutSeq;
  try{const r=await fetch('/api/state'+wq());if(!r.ok)return;const d=await r.json();
    if(busyUI()||seq!==mutSeq)return;
    if(viewWeek&&!(d.weeks||[]).some(w=>w.id===viewWeek)){viewWeek=null;return load()}
    const sig=x=>JSON.stringify([x.week&&x.week.id,x.week&&x.week.confirmed,(x.weeks||[]).map(w=>w.id+':'+w.confirmed),
      (x.meals||[]).map(m=>[m.id,m.day,m.status,m.name,m.steps.length,m.servings,m.disliked,m.filling,m.alts&&m.alts.length,m.bal&&m.bal.level,m.bal&&m.bal.g]),
      x.shopping,x.offers,x.pantry,x.cravings,x.todo,(x.recipes||[]).map(r=>r.id),(x.dislikes||[]).map(r=>r.id),x.servings_default]);
    if(sig(d)===sig(S))return;
    todoDiff(S.todo,d.todo);
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
  if(document.hidden||busyUI()||custOpen||sheet||cook||Date.now()-verAt<60000)return;verAt=Date.now();
  try{const r=await fetch('/',{cache:'no-store'});if(!r.ok)return;const v=verOf(await r.text());
    if(!v||v===myVer||sessionStorage.getItem('reloadedFor')===v)return;
    sessionStorage.setItem('reloadedFor',v);location.reload()}catch(e){}}
checkVersion();setInterval(checkVersion,600000);
document.addEventListener('visibilitychange',checkVersion);
window.addEventListener('focus',checkVersion);
