"use strict";
const $ = id => document.getElementById(id);
const categories = {audio:tr("Hörbücher"),audilege:"Audilege",ebook:"E-Books",podcast:"Podcasts"};
const media = $("audio");
let books=[], subscriptions=[], category="", current=null, publication=null, position=null, chapter=0, cues=[], cueIndex=-1;
let convertBook=null, absData=null, timer=null, saveQueue=Promise.resolve(), activeSpans=[];
let loadedAudio="",loadedChapter=-1, loading=false, generation=0, dirty=false, pendingSeek=null, segmentStart=null;
let anchorNodes=new Map(),sentenceNodes=new Map(),frame=0;
let account=null, sources={}, readerMode="read",shelfRevision="",readerRequest=0;
const audioTypes=".mp3,.m4b,.m4a,.ogg,.wav,.flac";
function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function message(s){$("message").textContent=s;}
function hint(e){message(e.message);}
async function api(path,method="GET",data){
  const options={method};
  if(path==="web/login"||path==="web/logout"){
    data={...data,cookiePath:new URL(".",document.baseURI).pathname};
  }
  if(data!==undefined){options.headers={"Content-Type":"application/json"};options.body=JSON.stringify(data);}
  const r=await fetch(path,options);
  const v=await r.json();
  if(!r.ok)throw new Error(tr(v.error)||tr("Anfrage fehlgeschlagen."));
  return v;
}
function show(id){for(const k of ["shelf","reader","statistics","users","profileView","settingsView"])$(k).hidden=k!==id;
  $("globalTools").hidden=id==="reader";
  if(narrowScreen.matches)setDrawer(false);
  for(const [k,v] of [["libraryNav",id==="shelf"||id==="reader"],["statsNav",id==="statistics"],["usersNav",id==="users"]]){
    if(v)$(k).setAttribute("aria-current","page");else $(k).removeAttribute("aria-current");
  }
  message("");
}
async function home(){readerRequest++;await closeReader();show("shelf");await refresh();}
let refreshSequence=0;
async function refresh(initial=false){
  const sequence=++refreshSequence;
  const preview=initial&&shelfPage==="start";
  const result=await api("web/library"+(preview?"?view=start":""));
  if(sequence!==refreshSequence)return;
  books=result.books;subscriptions=result.subscriptions;shelfRevision=JSON.stringify(result.revision);
  account=result.account;sources=result.sources||{};$("accountName").textContent=account.name;$("usersNav").hidden=!account.is_admin;
  libraryLinks=result.links||[];$("versionNav").textContent="Audilege Server "+result.version;
  renderShelf();
  const jobs=$("jobs");jobs.replaceChildren();
  const pending=result.jobs.filter(j=>j.state!=="done");
  if(pending.length)jobs.append(el("h2",tr("Aufträge")));
  for(const j of pending){
    const row=el("div",null,"panel jobRow");
    row.append(el("span",j.title+" · "+({waiting:tr("In Warteschlange"),running:j.note||tr("Abgleich wird gestartet"),failed:j.note}[j.state])));
    if(j.state==="failed"){
      const retry=el("button",tr("Erneut versuchen"));
      retry.onclick=async()=>{retry.disabled=true;try{await api("web/jobs/"+j.id+"/retry","POST",{});await refresh();}catch(e){hint(e);retry.disabled=false;}};
      row.append(retry);
    }
    jobs.append(row);
  }
  clearTimeout(timer);if(pending.some(j=>["running","waiting"].includes(j.state)))timer=setTimeout(()=>{if(!$("shelf").hidden)refresh().catch(hint);},3500);
  if(preview)requestAnimationFrame(()=>{if(sequence===refreshSequence)refresh().catch(hint);});
}
function renderShelf(){
  if(renderCollection())return;
  const term=$("bookSearch").value.trim().toLocaleLowerCase();
  const visible=books.filter(b=>[b.title,...b.authors.map(a=>a.name),b.metadata?.tags,b.metadata?.series,b.podcast?.show,b.podcast?.creator].join(" ").toLocaleLowerCase().includes(term));
  const groups=Object.keys(categories).filter(k=>books.some(b=>b.category===k)||(k==="podcast"&&subscriptions.length));
  if(category&&!groups.includes(category))category="";
  visible.sort(compareBooks);
  renderSidebarCategories(groups);
  renderResume(!term&&!category&&!discovering);
  $("shelfTitle").textContent=categories[category]||(discovering?tr("Entdecken"):tr("Bibliothek"));
  $("folderBack").hidden=!category&&!discovering;
  const filters=$("categories");filters.replaceChildren();
  if(groups.length>1)for(const k of ["",...groups]){
    const button=el("button",categories[k]||tr("Alle"));button.setAttribute("aria-pressed",String(k===category));
    button.onclick=()=>{category=k;podcastFilter="";allEpisodes=false;renderShelf();};filters.append(button);
  }
  const shelf=$("books");shelf.replaceChildren();
  if(!groups.length)shelf.append(el("p",tr("Deine Bibliothek ist leer. Füge ein EPUB, ein Hörbuch oder eine Podcastfolge hinzu."),"empty"));
  if(category==="podcast"){podcastShelf(shelf,visible.filter(b=>b.category==="podcast"),term);return;}
  if(discovering&&!category){
    const grid=el("div",null,"grid");
    for(const b of visible.filter(b=>b.category!=="podcast"))grid.append(bookTile(b));
    if(grid.childElementCount)shelf.append(grid);
    if(groups.includes("podcast"))podcastOverview(shelf,term);
    if(!shelf.children.length)shelf.append(el("p",tr("Keine passenden Titel gefunden."),"empty"));
    return;
  }
  for(const k of groups.filter(k=>!category||k===category)){
    if(k==="podcast"){podcastOverview(shelf,term);continue;}
    if(!visible.some(b=>b.category===k))continue;
    shelf.append(el("h2",categories[k]));
    const grid=el("div",null,"grid");shelf.append(grid);
    appendBookPage(grid,visible.filter(b=>b.category===k));
  }
  if(!shelf.children.length)shelf.append(el("p",tr("Keine passenden Titel gefunden."),"empty"));
}
function bookTile(book){
  const button=el("button",null,"book");
  button.append(cover(book),el("strong",book.title),el("small",book.authors.map(a=>a.name).join(", ")));
  if($("showSeries").checked&&book.metadata?.series){
    const volume=String(book.metadata.volume??"").trim();
    button.append(el("small",[book.metadata.series,volume&&tr("Band")+" "+volume].filter(Boolean).join(" · ")));
  }
  if(!$("shelfSort").hidden&&["location","locationDesc"].includes($("shelfSort").value)){
    const location=el("small",storageLabel(book),"shelfLocation");
    location.title=location.textContent;button.append(location);
  }
  if(book.played)button.append(el("small",tr("Gespielt")));
  if(book.readingProgress>0)button.append(el("small",Math.round(book.readingProgress)+" %"));
  button.onclick=()=>openReader(book).catch(hint);return button;
}
$("bookSearch").oninput=renderShelf;
setInterval(async()=>{
  if(!account||document.hidden||$("shelf").hidden||document.querySelector("dialog[open]"))return;
  try{
    const revision=await api("web/library/revision");
    if(JSON.stringify(revision)!==shelfRevision)await refresh();
  }catch(e){hint(e);}
},15000);
function imports(b=null){
  convertBook=b;$("importForm").reset();$("importStatus").textContent="";$("importGo").disabled=false;
  $("rssOption").hidden=!account?.is_admin;resetFeed();
  $("importTitle").textContent=b?tr("Audilege-Fassung erstellen"):tr("Titel hinzufügen");
  $("typeLabel").hidden=!!b;$("langLabel").hidden=!b;configure();$("importDialog").showModal();
  const matches=b?books.filter(other=>other.category===(b.category==="ebook"?"audio":"ebook")):[];
  $("companion").replaceChildren(new Option(tr("Datei hochladen"),""),...matches.map(other=>new Option(other.title+" · "+other.authors.map(a=>a.name).join(", "),other.id)));
  $("companionLabel").hidden=!matches.length;$("companion").value="";sourceChoice();
  const preferred=libraryLinks.find(r=>r.kind==="companion"&&(r.book===b?.id||Number(r.target)===b?.id));
  if(preferred){const other=preferred.book===b.id?Number(preferred.target):preferred.book;if(matches.some(x=>x.id===other)){$("companion").value=String(other);sourceChoice();}}
}
function sourceChoice(){const file=!$("companion").value;$("files").required=file;$("files").parentElement.hidden=!file;
  $("fileOrder").hidden=!file;if(!file)$("files").value="";}
$("companion").onchange=sourceChoice;
function configure(){
  const audio=convertBook?convertBook.category==="ebook":$("type").value!=="ebook";
  const rss=!convertBook&&$("type").value==="rss";
  $("rssControls").hidden=!rss;$("feedUrl").required=rss;
  $("files").accept=audio?audioTypes:".epub";$("files").multiple=audio;
  $("titleLabel").hidden=$("authorLabel").hidden=!audio||!!convertBook;
  $("filesLabel").textContent=audio?tr("Hördateien"):tr("EPUB-Datei");
  $("fileOrder").textContent=audio?tr("Mehrere Dateien werden nach Dateinamen abgespielt."):"";
  $("importGo").textContent=convertBook?tr("Abgleich starten"):tr("Hinzufügen");
  $("files").parentElement.hidden=rss;$("files").required=!rss;$("fileOrder").hidden=rss;
  if(rss){$("titleLabel").hidden=$("authorLabel").hidden=true;feedModeUI();knownFeeds().catch(hint);}
}
$("type").onchange=()=>{$("files").value="";configure();};
$("add").onclick=()=>imports();
$("convert").onclick=()=>imports(current);
$("importForm").onsubmit=async e=>{
  if(!convertBook&&$("type").value==="rss"){e.preventDefault();await importFeed();return;}
  e.preventDefault();$("importGo").disabled=true;
  try{
    const files=[...$("files").files].sort((a,b)=>a.name.localeCompare(b.name,"de",{numeric:true}));const ids=[];
    for(const [i,f] of files.entries()){
      $("importStatus").textContent=tr("Übertrage ")+(i+1)+tr(" von ")+files.length+" · "+f.name;
      const r=await fetch("web/uploads?name="+encodeURIComponent(f.name),{method:"POST",body:f});const v=await r.json();if(!r.ok)throw new Error(v.error);ids.push(v.upload);
    }
    $("importStatus").textContent=tr("Dateien prüfen …");
    if(convertBook)await api("web/align","POST",{book:convertBook.id,files:ids,language:$("lang").value,companion:Number($("companion").value)||null});
    else await api("web/books","POST",{files:ids,category:$("type").value,title:$("newTitle").value,author:$("newAuthor").value});
    $("importDialog").close();await home();
  }catch(error){$("importStatus").textContent=error.message;}finally{$("importGo").disabled=false;}
};
function duration(sec){
  sec=Number(sec)||0;const m=Math.floor(sec/60);return m>=60?Math.floor(m/60)+" h "+m%60+" min":m?m+" min":Math.round(sec)+" s";
}
function progressText(p){return p==null?"":Math.round(100*p)+" %";}
async function statistics(){
  await closeReader();show("statistics");
  const s=await api("web/statistics"),body=$("statsBody");body.replaceChildren();
  function section(title,rows){if(!rows.length)return;body.append(el("h2",title));const panel=el("div",null,"panel");body.append(panel);
    for(const [name,value] of rows){const row=el("div",null,"row");row.append(el("span",name),el("strong",value));panel.append(row);}
  }
  listeningDashboard(body,s);
  for(const [kind,label] of [["listen","Hören"],["read","Lesen"],["tts","Vorlesen"]]){
    const rows=Object.values(s.activities[kind]?.books||{}).sort((a,b)=>b.millis-a.millis);
    section(tr(label),rows.map(r=>[r.title,duration(r.millis/1000)]));
  }
  section(tr("Fortschritt aus Audiobookshelf"),s.positions.map(r=>[r.title,[r.finished?tr("Abgeschlossen"):"",r.ebook!=null?tr("Lesen ")+progressText(r.ebook):"",r.audio!=null?tr("Hören ")+progressText(r.audio):""].filter(Boolean).join(" · ")]));
}
$("absOpen").onclick=()=>{absData=null;$("absFile").value="";$("absGo").disabled=true;$("preview").textContent="";$("absDialog").showModal();};
let previewId=0;
$("absFile").onchange=async()=>{
  const seq=++previewId;$("absGo").disabled=true;absData=null;
  try{const file=$("absFile").files[0];if(!file)return;
    if(file.size>32*1024*1024)throw new Error(tr("Die Datei ist größer als 32 MB."));
    const data=JSON.parse(await file.text()),r=await api("web/abs/preview","POST",data);
    if(seq!==previewId)return;absData=data;$("preview").textContent=r.source+"\n"+r.newSessions+tr(" neue Hörsitzungen · ")+duration(r.addedSeconds)+" zusätzliche Hörzeit\n"+r.progressRecords+tr(" Fortschrittseinträge");
    $("absGo").disabled=false;
  }catch(e){if(seq===previewId)$("preview").textContent=e.message;}
};
$("absGo").onclick=async()=>{if(!absData)return;$("absGo").disabled=true;
  try{await api("web/abs/import","POST",absData);$("absDialog").close();await statistics();message(tr("Statistik importiert."));}
  catch(e){$("preview").textContent=e.message;$("absGo").disabled=false;}
};
function section(){return publication.sections[chapter];}
const timelines=new WeakMap();
function offsets(items,duration){
  if(!timelines.has(items)){
    const times=[0];for(const item of items)times.push(times.at(-1)+duration(item));
    timelines.set(items,times);
  }
  return timelines.get(items);
}
function cueTimes(list){return offsets(list,c=>c.end-c.begin);}
function partDuration(s){return cueTimes(s.cues).at(-1);}
function globalOffset(i){return offsets(publication.sections,partDuration)[i];}
function offsetOf(index){return cueTimes(cues)[Math.max(0,index)]||0;}
function within(){const c=cues[cueIndex];return c?Math.max(0,Math.min(c.end-c.begin,(pendingSeek??media.currentTime)-c.begin)):0;}
const resumeTab=sessionStorage.getItem("audilege-resume-tab")||Array.from(crypto.getRandomValues(new Uint32Array(3))).join("-");
sessionStorage.setItem("audilege-resume-tab",resumeTab);
function resumePrefix(){const mount=new URL(".",document.baseURI).pathname;
  const scope=mount==="/"?"":"mount="+encodeURIComponent(mount)+":";
  return "audilege-position:"+scope+encodeURIComponent(account.name)+":";}
async function sendPosition(key){
  const raw=localStorage.getItem(key);if(!raw)return;
  const item=JSON.parse(raw),entry=item.entry;
  let result=(await api("api/v1/reading-progress","PUT",{writes:[entry]})).results[0];
  if(result.status==="superseded"){
    const p=result.progress;
    const local=tr("Dieses Gerät")+" · "+Math.round(entry.percentage)+" %",remote="Server · "+Math.round(p.percentage)+" %";
    const matching=entry.kind==="text"?p.text.page===entry.text.page&&p.text.webOffset===entry.text.webOffset:
      p.narration.fragment===entry.narration.fragment&&p.narration.seconds===entry.narration.seconds;
    if(!(matching&&p.percentage===entry.percentage)){
      const keep=confirm(item.title+"\n"+local+"\n"+remote+"\n\n"+tr("Gerätestand übernehmen? Abbrechen übernimmt den Serverstand."));
      if(keep){
        entry.editedAt=p.updatedAt;
        result=(await api("api/v1/reading-progress","PUT",{writes:[entry]})).results[0];
        if(result.status!=="saved")throw Error(tr("Der Stand wurde erneut geändert."));
      }else if(publication?.fileId===entry.fileId){
        media.pause();dirty=false;loading=true;message(tr("Serverstand übernommen. Öffne den Titel erneut."));
      }
    }
  }
  if(localStorage.getItem(key)===raw)localStorage.removeItem(key);
  else {
    const newer=JSON.parse(localStorage.getItem(key)||"null");
    if(newer&&newer.entry.editedAt===item.base){newer.entry.editedAt=result.progress.updatedAt;newer.base=result.progress.updatedAt;localStorage.setItem(key,JSON.stringify(newer));}
  }
  if(publication?.fileId===entry.fileId)position=result.progress;
}
function retryPositions(){
  if(!account)return saveQueue;
  const prefix=resumePrefix();
  for(const k of Object.keys(localStorage).filter(k=>k.startsWith(prefix))){
    saveQueue=saveQueue.then(()=>sendPosition(k)).catch(hint);
  }
  return saveQueue;
}
window.addEventListener("online",retryPositions);
function queueProgress(){
  if(!publication||!dirty||loading)return saveQueue;
  const fileId=publication.fileId,gen=generation,sec=section(),c=isPaged()?null:cues[cueIndex];
  const elapsed=c?offsetOf(cueIndex)+within():0;
  const entry={fileId,kind:c?"narration":"text",percentage:100*(chapter+(c?elapsed/Math.max(.001,partDuration(sec)):0))/publication.sections.length};
  if(c){
    const seconds=globalOffset(chapter)+elapsed;
    entry.narration={seconds,fragment:c.anchor,sectionIndex:chapter};
    entry.percentage=Math.min(100,seconds*100/Math.max(.001,globalOffset(publication.sections.length)));
  }
  else {
    entry.text={page:chapter+1,webOffset:pageOffset,cfi:cfiAt(pageOffset)};
    entry.percentage=100*(chapter+pageOffset/Math.max(1,pageContent.length))/publication.sections.length;
  }
  const key=resumePrefix()+fileId+":"+resumeTab;
  entry.editedAt=position?.updatedAt||"1970-01-01T00:00:00.000Z";
  localStorage.setItem(key,JSON.stringify({title:current.title,base:entry.editedAt,entry}));
  dirty=false;
  saveQueue=saveQueue.then(()=>sendPosition(key)).catch(e=>{if(gen===generation&&navigator.onLine)hint(e);});
  return saveQueue;
}
function recordListening(){
  if(!segmentStart||!publication)return;
  const end=Date.now(),start=segmentStart;segmentStart=null;
  const seconds=Math.floor((end-start)/1000);if(seconds<1)return;
  const sessionId=Array.from(crypto.getRandomValues(new Uint32Array(4))).join("-");
  api("api/v1/books/files/"+publication.fileId+"/sessions","POST",{sessionId,startedAt:new Date(start).toISOString(),endedAt:new Date(end).toISOString(),durationSeconds:seconds,sessionType:"listen"}).catch(hint);
}
async function closeReader(){
  if(!current)return;
  resetReadingTools();
  resetDock();finishReadSession();
  recordListening();media.pause();await queueProgress();generation++;publication=null;current=null;loadedAudio="";loadedChapter=-1;pendingSeek=null;
  media.removeAttribute("src");media.load();activeSpans=[];loading=false;
}
function renderText(){
  const node=$("text"),s=section();node.replaceChildren();activeSpans=[];node.lang=publication.language;
  anchorNodes=new Map();sentenceNodes=new Map();
  for(const [text,anchor,sentence] of s.tokens){
    if(!anchor&&!sentence&&text==="\n"){node.append(el("br"));continue;}
    if(!anchor&&!sentence){node.append(document.createTextNode(text));continue;}
    const span=el("span",text);span.dataset.anchor=anchor;span.dataset.sentence=sentence;node.append(span);
    for(const [map,key] of [[anchorNodes,anchor],[sentenceNodes,sentence]])if(key){
      if(!map.has(key))map.set(key,[]);map.get(key).push(span);
    }
  }
  const hasTimedWords = s.wordTiming || s.cues.some(cue => {
    const sentence = anchorNodes.get(cue.anchor)?.[0]?.dataset.sentence;
    return sentence && sentence !== cue.anchor;
  });
  $("modeWrap").hidden=!hasTimedWords;
  highlight();
}
function highlight(){
  for(const n of activeSpans)n.classList.remove("current");activeSpans=[];
  const c=cues[cueIndex];if(!c)return;
  const word=anchorNodes.get(c.anchor);
  const sentenceCue=sentenceNodes.get(c.anchor);
  const target=word?.[0] || sentenceCue?.[0];if(!target)return;
  const sentenceGroup=sentenceNodes.get(target.dataset.sentence);
  activeSpans=sentenceCue || ($("mode").value==="sentence" && sentenceGroup) || word;
  for(const n of activeSpans)n.classList.add("current");
  if(readerMode==="along"&&!media.paused&&followPassage){const r=target.getBoundingClientRect();if(r.top<100||r.bottom>innerHeight-80)target.scrollIntoView({block:"center",behavior:"instant"});}
}
$("mode").value=localStorage.getItem("audilege-mark")||"word";
$("mode").onchange=()=>{localStorage.setItem("audilege-mark",$("mode").value);highlight();};
function setCue(i,offset=0,play=false){
  cueIndex=i;const c=cues[i];if(!c)return;highlight();
  loadedChapter=chapter;
  const url="api/v1/epub/"+current.id+"/media-overlay/file/"+c.path.split("/").map(encodeURIComponent).join("/")+"?fileId="+publication.fileId;
  const t=c.begin+Math.max(0,Math.min(offset,c.end-c.begin));
  if(url!==loadedAudio){
    loadedAudio=url;pendingSeek=t;
    media.src=url;media.load();
  }else if(Math.abs(media.currentTime-t)>.08){pendingSeek=t;media.currentTime=t;}
  if(play&&!isPaged())media.play().catch(hint);
}
media.onloadedmetadata=()=>{if(pendingSeek!=null){media.currentTime=pendingSeek;pendingSeek=null;}};
media.onseeked=()=>{pendingSeek=null;if(!loading&&!isPaged())dirty=true;updateCue();if(media.paused)queueProgress();};
function setChapter(i){
  finishReadSession();
  currentPassage=null;pageRuns=[];
  chapter=i;$("chapter").value=String(i);cues=section().cues;cueIndex=cues.length?0:-1;
  syncMode(0);
  if(!cues.length){media.pause();media.removeAttribute("src");media.load();loadedAudio="";}
}
function nextSection(play){
  if(stopAtChapter){stopAtChapter=false;media.pause();dirty=true;queueProgress();return;}
  if(chapter+1>=publication.sections.length){media.pause();dirty=true;queueProgress();if(play)advanceQueue().catch(hint);return;}
  let i=chapter+1;while(i<publication.sections.length&&!publication.sections[i].cues.length)i++;
  if(i===publication.sections.length){media.pause();dirty=true;queueProgress();return;}
  setChapter(i);if(cues.length)setCue(0,0,play);dirty=true;
}
function updateCue(){
  if(loading||!current||!cues.length||pendingSeek!=null)return;
  const c=cues[cueIndex],time=media.currentTime;if(!c)return;
  if(time>=c.begin && time<c.end)return;
  const next=cues[cueIndex+1];
  if(next && next.path===c.path && time>=c.end && time<next.begin)return;
  if(next && next.path===c.path && time>=next.begin && time<next.end){cueIndex++;highlight();return;}
  if(next && next.path===c.path && time>=next.end && next.begin>=c.begin){
    // Several short marks can elapse between frames, especially after a background tab resumes.
    // Follow the media clock through contiguous marks, including the silence between them.
    let last=cueIndex+1;
    while(last+1<cues.length && cues[last+1].path===c.path && cues[last+1].begin>=cues[last].begin && cues[last+1].begin<=time)last++;
    cueIndex=last;highlight();return;
  }
  const i=cues.findIndex(q=>q.path===c.path&&q.begin<=time&&time<q.end);
  if(i>=0){cueIndex=i;highlight();return;}
  if(!media.paused&&time>=c.end){
    if(cueIndex+1<cues.length)setCue(cueIndex+1,0,true);
    else nextSection(true);
  }
}
media.ontimeupdate=()=>{if(!media.paused&&!loading)dirty=true;updateCue();};
function follow(){if(media.paused||!publication)return;updateCue();frame=requestAnimationFrame(follow);}
media.onplaying=()=>{if(!loading)segmentStart??=Date.now();cancelAnimationFrame(frame);frame=requestAnimationFrame(follow);};
media.onwaiting=recordListening;
media.onpause=()=>{recordListening();if(current)queueProgress();};
media.onended=()=>{if(!publication||loading)return;dirty=true;if(cueIndex+1<cues.length)setCue(cueIndex+1,0,true);else nextSection(true);};
$("chapter").onchange=()=>{const playing=!media.paused;setChapter(Number($("chapter").value));if(cues.length)setCue(0,0,playing);dirty=true;queueProgress();};
$("text").onclick=e=>{if(!e.target.dataset?.anchor)return;let i=cues.findIndex(q=>q.anchor===e.target.dataset.anchor);
  if(i<0 && e.target.dataset.sentence)i=cues.findIndex(q=>q.anchor===e.target.dataset.sentence);
  if(i>=0){setCue(i,0,!media.paused);dirty=true;queueProgress();}};
async function openReader(book,resume=false,requestedMode=null){
  const request=++readerRequest;
  await closeReader();if(request!==readerRequest)return;
  current=book;show("reader");$("reader").dataset.category=book.category;
  $("readerTitle").textContent=book.title;$("author").textContent=book.authors.map(a=>a.name).join(", ");
  $("convert").hidden=!["audio","ebook"].includes(book.category);
  $("download").hidden=!["ebook","audilege"].includes(book.category);
  $("download").href="api/v1/books/files/"+book.files[0].id+"/download";
  configureBook();
  $("reader").dataset.mode="detail";$("detailHero").hidden=false;$("activeBook").hidden=true;$("readerModes").hidden=true;
  $("back").textContent=category==="podcast"?"← Podcasts":tr("← Bibliothek");
  if(!resume)return;
  const pub=await api("web/editions/"+book.id);
  if(request!==readerRequest)return;
  const row=(await api("api/v1/reading-progress?fileId="+pub.fileId)).items[0];
  if(request!==readerRequest)return;
  loading=true;publication=pub;position=row;dirty=false;
  const recentText=row.text.updatedAt && (!row.narration.updatedAt||row.text.updatedAt>row.narration.updatedAt);
  readerMode=requestedMode||(book.category==="audilege"?(recentText?"read":"along"):book.category==="ebook"?"read":"listen");
  $("detailHero").hidden=true;$("activeBook").hidden=false;$("readerModes").hidden=false;$("back").textContent=tr("← Buchdetails");
  $("chapter").replaceChildren(...pub.sections.map((s,i)=>new Option(s.name,String(i))));
  let index=row.narration.sectionIndex??Math.floor(row.percentage*pub.sections.length/100);
  if(recentText){
    const match=/^epubcfi\(\/\d+\/(\d+)(?:\[[^\]]*\])?!/.exec(row.text.cfi||"");
    index=match?Number(match[1])/2-1:(row.text.page?row.text.page-1:Math.floor(row.percentage*pub.sections.length/100));
  }
  index=Math.max(0,Math.min(index,pub.sections.length-1));
  if(!isPaged()&&!pub.sections[index].cues.length){
    const next=pub.sections.findIndex((s,i)=>i>=index&&s.cues.length);
    if(next>=0)index=next;
  }
  setChapter(index);
  const model=await getPassage(pub,index,book);
  if(request!==readerRequest || publication!==pub || chapter!==index)return;
  currentPassage=model;
  const fromText=recentText?(row.text.webOffset!=null && /!\/4\)$/.test(row.text.cfi||"")?row.text.webOffset:
    fromCfi(model,row.text.cfi)??row.text.webOffset??0):0;
  if(cues.length){
    const i=recentText?cueAtOffset(fromText):Math.max(0,cues.findIndex(c=>c.anchor===row.narration.fragment));
    const fromSeconds=(row.narration.seconds??0)-globalOffset(chapter)-offsetOf(i);
    const fromFraction=((row.narration.percentage??0)*pub.sections.length/100-chapter)*partDuration(section())-offsetOf(i);
    setCue(i,recentText?0:fromSeconds>.02?fromSeconds:Math.max(0,fromFraction));
  }
  loading=false;
  if(isPaged())syncMode(recentText?fromText:model?.anchors.get(cues[cueIndex]?.anchor)??0);
}
setInterval(()=>{if(!media.paused){queueProgress();recordListening();segmentStart=Date.now();}},5000);
document.addEventListener("visibilitychange",()=>{if(document.hidden){queueProgress();recordListening();if(!media.paused)segmentStart=Date.now();}});
$("back").onclick=()=>($("detailHero").hidden&&current?openReader(current):home()).catch(hint);
function resetShelf(){shelfPage="library";facetValue="";category="";discovering=false;podcastFilter="";allEpisodes=false;$("bookSearch").value="";}
$("libraryNav").onclick=()=>{resetShelf();home().catch(hint);};
$("folderBack").onclick=()=>{resetShelf();renderShelf();};
$("statsNav").onclick=()=>statistics().catch(hint);
document.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>b.closest("dialog").close());
async function enter(){await refresh(true);$("loginView").hidden=true;$("shell").hidden=false;await retryPositions();}
$("loginForm").onsubmit=async e=>{e.preventDefault();try{await api("web/login","POST",Object.fromEntries(new FormData(e.target)));e.target.reset();$("loginError").textContent="";await enter();}catch(e){$("loginError").textContent=e.message;}};
$("logout").onclick=async()=>{try{await closeReader();await api("web/logout","POST",{});location.reload();}catch(e){hint(e);}};
document.addEventListener("DOMContentLoaded",()=>enter().catch(()=>{$("loginView").hidden=false;}));
