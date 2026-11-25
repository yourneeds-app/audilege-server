"use strict";
let pageContent="",pageOffset=0,pageIndex=0,pageCount=1;
let readStart=0,readKind="",dockTimer=0,adjustingSeek=false;
const modeLabels={read:tr("Lesen"),listen:tr("Hören"),along:tr("Mitlesen")};
function isPaged(){return readerMode==="read";}
function configureBook(book=detailBook){
  enqueueButton.hidden=book.category==="ebook";playedButton.hidden=book.category!=="podcast";
  const modes=$("readerModes"),entries=$("entryModes");modes.replaceChildren();entries.replaceChildren();
  const options=book.category==="audilege"?["read","listen","along"]:book.category==="ebook"?["read"]:["listen"];
  for(const mode of options){
    const b=el("button",modeLabels[mode]);b.dataset.mode=mode;
    b.onclick=async()=>{try{await changeMode(mode);}catch(e){hint(e);}};modes.append(b);
    const entry=el("button",modeLabels[mode]);entry.dataset.mode=mode;entry.onclick=()=>openReader(book,true,mode).catch(hint);entries.append(entry);
  }
  $("reader").querySelector(".more").open=false;$("metaOpen").hidden=!account?.is_admin;
  $("mediumKind").textContent={ebook:"E-Book",audilege:"Audilege",audio:tr("Hörbuch"),podcast:"Podcast"}[book.category];
  $("detailArt").replaceChildren(cover(book,book.category==="audilege"?"book":""));
  $("listenArt").replaceChildren(cover(book,"audio"));showBookInfo();
  $("audioTitle").textContent=book.title;
  const narrator=creditedNarrator(book);
  $("audioCredit").textContent=narrator?tr("Gelesen von")+" "+narrator:creditedAuthors(book).join(", ");
  $("audioKind").textContent=book.category==="podcast"?"Podcast":tr("Hörbuch");
}
async function changeMode(mode) {
  if(mode===readerMode||!current)return;
  const wasReading=isPaged(),wasPlaying=!media.paused;
  const pub=publication,index=chapter;
  if(!pub||loading)return;
  const model=await getPassage(pub,index,current);
  if(publication!==pub||chapter!==index)return;
  currentPassage=model;
  const savedOffset=wasReading?pageOffset:(model?.anchors.get(cues[cueIndex]?.anchor)??0);
  finishReadSession();media.pause();await queueProgress();if(!publication)return;
  readerMode=mode;
  if(!isPaged()&&!cues.length){
    const next=publication.sections.findIndex((s,i)=>i>=chapter&&s.cues.length);
    const i=next<0?publication.sections.findIndex(s=>s.cues.length):next;
    if(i>=0)setChapter(i);
  }
  if(!isPaged()&&cues.length){
    if(wasReading)setCue(cueAtOffset(savedOffset));
    else if(!loadedAudio||loadedChapter!==chapter)setCue(Math.max(0,cueIndex));
  }
  syncMode(savedOffset);
  dirty=true;
  await queueProgress();
  if(wasPlaying&&!isPaged())await media.play();
}
function syncMode(offset) {
  readerControls();
  $("reader").classList.remove("focusPaper");
  paperHeading.textContent=section().name;paperHeading.hidden=readerMode==="listen";
  for(const b of $("readerModes").children)b.setAttribute("aria-pressed",String(b.dataset.mode===readerMode));
  const paged=isPaged(),listen=readerMode==="listen";
  if(!$("activeBook").hidden)$("reader").dataset.mode=readerMode;
  $("text").hidden=readerMode!=="along";$("paged").hidden=!paged;$("player").hidden=paged||!cues.length;
  $("listenArt").hidden=$("audioHeading").hidden=!listen;$("listenChapter").textContent=section().name;
  $("chapterWrap").hidden=listen;$("hideDock").hidden=readerMode!=="along";
  const singleEpisode=current.category==="podcast"&&publication.sections.length===1;
  $("chapterList").hidden=!listen||singleEpisode;
  $("listenChapter").hidden=$("chapterNumber").hidden=listen&&singleEpisode;
  resetDock();updateTransport();
  if(listen)renderChapters();
  if(readerMode!=="along")$("modeWrap").hidden=true;else {
    renderText();
    if(currentPassage)renderPassage($("text"),currentPassage,false);
    else layoutPassage(0).catch(hint);
  }
  if(paged){
    pageContent=section().lines.join("\n\n");$("pageText").lang=publication.language||"de";
    pageRuns=[];
    if(currentPassage)renderPassage($("pageText"),currentPassage,true);
    else {$("pageText").textContent=pageContent;layoutPassage(offset).catch(hint);}
    $("pageWindow").scrollLeft=0;positionPage(offset);
    if(readerMode==="read")startReadSession("read");
  }
}
function pageStep(){return $("pageWindow").clientWidth+24;}
function scrollReading(){return document.documentElement.dataset.flow==="scroll";}
function offsetCoordinate(offset) {
  const run=passageRun(pageRuns,offset),node=run?.node||$("pageText").firstChild;if(!node||!node.length)return 0;
  const pos=Math.min(Math.max(0,offset-(run?.start||0)),node.length-1),range=new Range();
  range.setStart(node,pos);range.setEnd(node,pos+1);
  const box=$("pageWindow");
  const r=range.getBoundingClientRect(),v=box.getBoundingClientRect();
  return scrollReading()?r.top-v.top+box.scrollTop:r.left-v.left+box.scrollLeft;
}
function pageAt(offset){
  const step=scrollReading()?$("pageWindow").clientHeight:pageStep();
  return Math.max(0,Math.min(pageCount-1,Math.floor((offsetCoordinate(offset)+1)/Math.max(1,step))));
}
function firstOffset(page) {
  if(!page)return 0;let lo=0,hi=pageContent.length;
  while(lo<hi){const mid=Math.floor((lo+hi)/2);if(pageAt(mid)<page)lo=mid+1;else hi=mid;}
  return lo;
}
function positionPage(offset){
  const view=$("pageWindow");if(!view.clientWidth)return;
  const text=$("pageText"),scroll=scrollReading();
  const columns=!scroll && view.clientWidth>=58*parseFloat(getComputedStyle(text).fontSize)?2:1;
  text.style.columnWidth="auto";text.style.columnCount=scroll?"auto":String(columns);
  text.classList.remove("padSpread");
  const columnCount=Math.round((view.scrollWidth+24)*columns/pageStep());
  if(columns===2&&columnCount>2&&columnCount%2)text.classList.add("padSpread");
  pageCount=scroll?Math.max(1,Math.ceil(view.scrollHeight/view.clientHeight)):Math.max(1,Math.ceil(columnCount/columns));
  pageOffset=Math.max(0,Math.min(Number(offset)||0,Math.max(0,pageContent.length-1)));
  pageIndex=pageAt(pageOffset);
  if(scrollReading())view.scrollTop=offsetCoordinate(pageOffset);else view.scrollLeft=pageIndex*pageStep();
  $("pageNumber").textContent=tr("Seite")+" "+(pageIndex+1)+" "+tr("von")+" "+pageCount;
  $("prevPage").disabled=chapter===0&&pageIndex===0;
  $("nextPage").disabled=chapter===publication.sections.length-1&&pageIndex===pageCount-1;
}
function turn(direction) {
  if(!publication||!isPaged())return;
  const n=pageIndex+direction;
  if(n>=0&&n<pageCount)positionPage(firstOffset(n));
  else if(publication.sections[chapter+direction]){
    setChapter(chapter+direction);if(direction<0)positionPage(firstOffset(pageCount-1));
  }else return;
  dirty=true;queueProgress();
}
$("prevPage").onclick=()=>turn(-1);$("nextPage").onclick=()=>turn(1);
let scrollSave=0;
$("pageWindow").addEventListener("scroll",()=>{
  if(!publication||!isPaged()||!scrollReading()||loading)return;
  const pub=publication,index=chapter;
  clearTimeout(scrollSave);
  scrollSave=setTimeout(()=>{
    if(pub!==publication||index!==chapter||!isPaged()||!scrollReading())return;
    const top=$("pageWindow").scrollTop;
    let lo=0,hi=pageContent.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(offsetCoordinate(mid)<top-1)lo=mid+1;else hi=mid;}
    if(pageOffset===lo)return;
    pageOffset=lo;pageIndex=pageAt(lo);$("pageNumber").textContent=tr("Seite")+" "+(pageIndex+1)+" "+tr("von")+" "+pageCount;
    $("prevPage").disabled=chapter===0&&pageIndex===0;
    $("nextPage").disabled=chapter===publication.sections.length-1&&top+$("pageWindow").clientHeight>=$("pageWindow").scrollHeight-2;
    dirty=true;queueProgress();
  },120);
});
$("pageText").addEventListener("click",e=>{
  if(!currentPassage||getSelection()?.toString())return;
  const pos=document.caretPositionFromPoint?.(e.clientX,e.clientY);
  const r=pos?null:document.caretRangeFromPoint?.(e.clientX,e.clientY);
  const run=pageRuns.find(v=>v.node===(pos?.offsetNode||r?.startContainer));
  if(run){pageOffset=run.start+(pos?.offset??r.startOffset);dirty=true;queueProgress();}
});
new ResizeObserver(()=>{if(publication&&isPaged()&&!$("reader").hidden)positionPage(pageOffset);}).observe($("pageWindow"));
let finger=null;
$("pageWindow").addEventListener("touchstart",e=>{finger=[e.touches[0].clientX,e.touches[0].clientY];},{passive:true});
$("pageWindow").addEventListener("touchend",e=>{
  if(!finger)return;const dx=e.changedTouches[0].clientX-finger[0],dy=e.changedTouches[0].clientY-finger[1];finger=null;
  if(Math.abs(dx)>55&&Math.abs(dx)>2*Math.abs(dy)&&!getSelection()?.toString())turn(dx<0?1:-1);
},{passive:true});
document.addEventListener("keydown",e=>{
  if(!current||!isPaged()||document.querySelector("dialog[open]")||e.target.matches("input,select,textarea,button,summary"))return;
  if(["ArrowLeft","ArrowRight"].includes(e.key)){e.preventDefault();turn(e.key==="ArrowLeft"?-1:1);}
});
function startReadSession(kind){if(!readStart&&!document.hidden){readStart=Date.now();readKind=kind;}}
function finishReadSession(){
  if(!readStart||!publication)return;
  const now=Date.now(),seconds=Math.floor((now-readStart)/1000),start=readStart;readStart=0;
  if(seconds>0)api("api/v1/books/files/"+publication.fileId+"/sessions","POST",{sessionId:Array.from(crypto.getRandomValues(new Uint32Array(4))).join("-"),startedAt:new Date(start).toISOString(),endedAt:new Date(now).toISOString(),durationSeconds:seconds,sessionType:readKind}).catch(hint);
}
document.addEventListener("visibilitychange",()=>{
  if(!publication||!isPaged())return;
  if(document.hidden)finishReadSession();else startReadSession("read");
});
setInterval(()=>{
  if(!publication||!isPaged()||document.hidden||!readStart)return;
  const kind=readKind;finishReadSession();startReadSession(kind);
},30000);
function skipAudio(delta){
  if(!cues.length)return;
  seekChapter(offsetOf(cueIndex)+within()+delta);
}
function seekChapter(seconds){
  if(!cues.length)return;
  const offset=Math.max(0,Math.min(partDuration(section())-.01,seconds));let at=0;
  if(adjustingSeek || Math.abs(offset-(offsetOf(cueIndex)+within()))>=60)rememberJump();
  for(let i=0;i<cues.length;i++){const end=at+cues[i].end-cues[i].begin;if(offset<end){setCue(i,offset-at,!media.paused);break;}at=end;}
  dirty=true;updateTransport();queueProgress();
}
$("skipBack").onclick=()=>skipAudio(-15);$("skipForward").onclick=()=>skipAudio(15);
$("audioSpeed").onchange=()=>{media.defaultPlaybackRate=media.playbackRate=Number($("audioSpeed").value);updateTransport();};
media.addEventListener("ratechange",updateTransport);

function clock(seconds){
  const s=Math.max(0,Math.floor(seconds||0)),hours=Math.floor(s/3600);
  const minutes=String(Math.floor(s/60)%60);
  return (hours?hours+":"+minutes.padStart(2,"0"):minutes)+":"+String(s%60).padStart(2,"0");
}
function renderChapters(){
  const list=$("trackRows");list.replaceChildren();
  for(const [i,s] of publication.sections.entries()){
    if(!s.cues.length)continue;
    const b=el("button");b.append(el("span",s.name),el("small",clock(partDuration(s))));
    if(i===chapter)b.setAttribute("aria-current","true");
    b.onclick=()=>{$("chapter").value=String(i);$("chapter").onchange();};list.append(b);
  }
}
function showRemaining(position,total){
  const chapterLeft=(total-position)/media.playbackRate;
  $("elapsed").textContent=clock(position);
  $("remaining").textContent=tr("Kapitel noch {time}").replace("{time}",clock(chapterLeft));
  const bookLeft=(globalOffset(publication.sections.length)-globalOffset(chapter)-position)/media.playbackRate;
  $("bookRemaining").hidden=current?.category==="podcast"||publication.sections.length<2;
  $("bookRemaining").textContent=tr("Buch noch {time}").replace("{time}",clock(bookLeft));
  $("undoAudioJump").hidden=jumpBack?.pub!==publication;
}
function updateTransport(){
  if(!publication||!cues.length)return;
  const total=partDuration(section()),time=offsetOf(cueIndex)+within();
  $("chapterNumber").textContent=tr("Kapitel ")+(chapter+1)+tr(" von ")+publication.sections.length;
  if(!adjustingSeek){$("chapterSeek").max=total;$("chapterSeek").value=time;$("chapterSeek").setAttribute("aria-valuetext",clock(time)+tr(" von ")+clock(total));}
  if(!adjustingSeek)showRemaining(time,total);
  $("audioPlay").textContent=media.paused?tr("Abspielen"):"Pause";
}
$("audioPlay").onclick=()=>{if(!publication)return;if(media.paused)media.play().catch(hint);else media.pause();};
$("chapterSeek").oninput=e=>{adjustingSeek=true;showRemaining(Number(e.target.value),Number(e.target.max));};
$("chapterSeek").onchange=e=>{seekChapter(Number(e.target.value));adjustingSeek=false;updateTransport();};
function resetDock(){
  clearTimeout(dockTimer);$("playerBody").hidden=false;$("showDock").hidden=true;adjustingSeek=false;
}
function foldDock(){
  if(readerMode!=="along"||!publication)return;
  $("playerBody").hidden=true;$("showDock").hidden=false;
  if($("playerBody").contains(document.activeElement))$("showDock").focus({preventScroll:true});
}
function armDock(){
  clearTimeout(dockTimer);
  if(readerMode!=="along"||media.paused||$("playerBody").hidden)return;
  dockTimer=setTimeout(()=>{if(!adjustingSeek&&!$("playerBody").querySelector(":focus-visible"))foldDock();},4000);
}
function revealDock(){resetDock();armDock();}
$("hideDock").onclick=foldDock;
$("showDock").onclick=()=>{revealDock();$("audioPlay").focus({preventScroll:true});};
$("text").addEventListener("click",()=>{if(readerMode==="along")revealDock();});
for(const name of ["pointermove","pointerup","keydown","focusout"])$("player").addEventListener(name,armDock);
for(const name of ["timeupdate","play","pause","loadedmetadata","seeked"])media.addEventListener(name,updateTransport);
media.addEventListener("playing",armDock);
media.addEventListener("pause",resetDock);
