"use strict";
function cover(book,variant="") {
  function fallback(){
    const placeholder=el("span",null,"art noCover");placeholder.setAttribute("aria-hidden","true");
    placeholder.append(el("span",book.title));return placeholder;
  }
  if(!book.cover&&!(variant==="audio"&&book.category==="audilege"))return fallback();
  const img=el("img",null,"art");img.alt="";img.onerror=()=>img.replaceWith(fallback());
  img.loading="lazy";img.decoding="async";
  img.src="/api/v1/books/"+book.id+(variant?"/cover?art=":"/thumbnail?size=360&art=")+(variant||(book.category==="audio"||book.category==="podcast"?"audio":"book"))+"&rev="+encodeURIComponent(shelfRevision);return img;
}
function renderResume(visible) {
  const box=$("resume");box.replaceChildren();
  const titles=books.filter(b=>b.category!=="podcast");
  const recent=titles.filter(b=>b.updatedAt && b.readingProgress<100).sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt))[0];
  const book=visible && (recent||titles.reduce((last,b)=>!last||b.files[0].id>last.files[0].id?b:last,null));
  box.hidden=!book;if(!book)return;
  const btn=el("button",null,"resumeCard"), info=el("span",null,"resumeText");
  info.append(el("small",recent?tr("Fortsetzen"):tr("Zuletzt hinzugefügt")),el("strong",book.title),el("span",book.authors.map(a=>a.name).join(", ")));
  const progress=el("progress");progress.max=100;progress.value=book.readingProgress;progress.setAttribute("aria-label",tr("Fortschritt"));
  if(recent)info.append(progress);btn.append(cover(book),info,el("span","→","resumeArrow"));
  btn.onclick=()=>openReader(book,!!recent).catch(hint);box.append(btn);
}

let editedUser=null, ownId=0;
async function listUsers() {
  await closeReader();show("users");
  selectAdminTab(false);
  const result=await api("/web/admin/users");ownId=result.self;
  const list=$("userList");list.replaceChildren();
  for(const user of result.users){
    const row=el("div",null,"accountRow"), identity=el("div");
    identity.append(el("strong",user.name),el("small",(user.is_admin?"Administrator":tr("Benutzer"))+(user.enabled?"":tr(" · Deaktiviert"))));
    const edit=el("button",tr("Bearbeiten"));edit.setAttribute("aria-label",user.name+" bearbeiten");edit.onclick=()=>userForm(user);
    if(user.email)identity.append(el("small",user.email));
    identity.append(action(tr("Gerätesitzungen"),()=>deviceSheet(user.id),"textButton"));
    row.append(el("span",user.name.slice(0,1).toLocaleUpperCase(),"avatar"),identity,edit);list.append(row);
  }
}
let inboxTimer;
function selectAdminTab(inbox){
  clearTimeout(inboxTimer);$("accountsTab").setAttribute("aria-pressed",String(!inbox));$("inboxTab").setAttribute("aria-pressed",String(inbox));
  $("userList").hidden=$("newUser").hidden=inbox;$("inboxPanel").hidden=!inbox;
}
async function inboxStatus(manual=false){
  clearTimeout(inboxTimer);
  const state=await api("/web/admin/inbox",manual?"POST":"GET",manual?{}:undefined);
  $("inboxPath").textContent=state.folder;
  $("folderDetails").hidden=!!state.fixed;
  if(!$("folderDetails").open)$("mediaFolder").value=state.folder;
  $("scanStatus").textContent=[manual?tr("Scan angefordert."):state.running?tr("Scan läuft …"):tr("Automatischer Scan alle ")+state.interval+tr(" Sekunden."),
    state.last?tr("Zuletzt geprüft um ")+new Date(state.last).toLocaleTimeString(uiLanguage)+".":"",
    state.waiting?state.waiting+" Quelle(n) werden auf vollständige Übertragung geprüft.":"",
    ...state.errors].filter(Boolean).join("\n");
  if(!$("users").hidden&&!$("inboxPanel").hidden)inboxTimer=setTimeout(()=>inboxStatus().catch(hint),2500);
}
$("accountsTab").onclick=()=>selectAdminTab(false);
$("inboxTab").onclick=()=>{selectAdminTab(true);inboxStatus().catch(hint);};
$("scanNow").onclick=()=>inboxStatus(true).catch(hint);
$("folderForm").onsubmit=async e=>{
  e.preventDefault();
  try{
    await api("/web/admin/inbox","POST",{folder:$("mediaFolder").value.trim()});
    $("folderDetails").open=false;await inboxStatus();
  }catch(err){message(err.message);}
};
function userForm(user=null) {
  editedUser=user;$("userForm").reset();$("userTitle").textContent=user?tr("Konto bearbeiten"):tr("Benutzer anlegen");$("userError").textContent="";
  $("userName").value=user?.name||"";$("userName").readOnly=!!user;
  $("passwordLabel").firstChild.nodeValue=user?tr("Neues Passwort (optional)"):tr("Passwort");$("userPassword").required=!user;
  $("userEnabled").checked=user?!!user.enabled:true;$("userEnabled").disabled=!user||user.id===ownId;
  $("userAdmin").checked=!!user?.is_admin;$("userAdmin").disabled=user?.id===ownId;$("userDialog").showModal();
}
$("usersNav").onclick=()=>listUsers().catch(hint);$("newUser").onclick=()=>userForm();
$("userForm").onsubmit=async e=>{
  e.preventDefault();const btn=e.submitter;btn.disabled=true;
  try{
    const pw=$("userPassword").value;
    await api("/web/admin/users"+(editedUser?"/"+editedUser.id:""),"POST",{name:$("userName").value,password:pw,
      admin:$("userAdmin").checked,enabled:$("userEnabled").checked});
    $("userDialog").close();$("userPassword").value="";
    if(editedUser?.id===ownId&&pw){location.reload();return;}
    await listUsers();
  }catch(err){$("userError").textContent=err.message;}finally{btn.disabled=false;}
};

const metadataFields={title:tr("Titel"),author:tr("Autor"),series:tr("Reihe"),volume:tr("Band"),narrator:tr("Sprecher"),year:tr("Erscheinungsjahr"),publisher:tr("Verlag"),isbn:"ISBN",tags:tr("Genres und Schlagwörter"),description:tr("Beschreibung")};
let metaSource="",lookupSeq=0,coverCandidate="";
function selectCover(url){
  coverCandidate=url||"";$("coverChoice").hidden=$("candidateCover").hidden=!url;$("useCover").checked=!!url;
  if(url)$("candidateCover").src=url;else $("candidateCover").removeAttribute("src");
}
function fillMeta(data) {
  for(const [key] of Object.entries(metadataFields))if(data[key])$("field-"+key).value=data[key];
  metaSource=data.source||"";
}
function showBookInfo(){
  const data=current.metadata||{},box=$("bookInfo");box.replaceChildren();
  if(current.updatedAt)box.append(el("p",tr("Fortschritt")+" · "+Math.round(current.readingProgress)+" %"));
  for(const link of libraryLinks.filter(l=>["duplicate","companion"].includes(l.kind)&&(l.book===current.id||Number(l.target)===current.id))){
    const other=books.find(b=>b.id===(link.book===current.id?Number(link.target):link.book));
    if(other)box.append(action((link.kind==="duplicate"?(uiLanguage==="de"?"Dublette":"Duplicate"):tr("Passende Ausgabe"))+" · "+other.title,()=>openReader(other),"textButton"));
  }
  const summary=[data.series,data.narrator&&(tr("Gelesen von ")+data.narrator),data.year].filter(Boolean).join(" · ");
  if(summary)box.append(el("p",summary));
  if(data.description||data.tags||data.isbn||data.publisher){
    const more=el("details");more.open=true;more.append(el("summary",tr("Buchinformationen")));
    for(const value of [data.description,data.tags,data.publisher,data.isbn&&("ISBN "+data.isbn)])if(value)more.append(el("p",value));
    box.append(more);
  }
  box.hidden=!box.childElementCount;
}
$("metaOpen").onclick=()=>{
  $("reader").querySelector(".more").open=false;$("matches").replaceChildren();$("metaStatus").textContent="";
  $("metaTerm").value=current.title;const fields=$("metaFields");fields.replaceChildren();
  for(const [key,name] of Object.entries(metadataFields)){
    const label=el("label",name),input=el(key==="description"?"textarea":"input");input.id="field-"+key;input.maxLength=2000;input.required=key==="title";
    label.append(input);fields.append(label);
  }
  fillMeta({...current.metadata,title:current.title,author:current.authors.map(a=>a.name).join(", ")});
  selectCover("");$("coverFile").value="";$("coverRole").value=["audio","podcast"].includes(current.category)?"audio":"book";$("resetCover").checked=false;
  const opts=$("sourceOptions");opts.replaceChildren(el("legend",tr("Suchanbieter")));
  let selected=Object.keys(sources);try{selected=JSON.parse(localStorage.getItem("audilege-catalogues"))??selected;}catch{}
  for(const [id,name] of Object.entries(sources)){
    const label=el("label",null,"check"),input=el("input");input.type="checkbox";input.value=id;input.checked=selected.includes(id);
    label.append(input,document.createTextNode(name));opts.append(label);
  }
  $("metadataDialog").showModal();
};
$("sourceOptions").onchange=()=>localStorage.setItem("audilege-catalogues",JSON.stringify(checkedSources()));
function checkedSources(){return Array.from($("sourceOptions").querySelectorAll("input:checked"),n=>n.value);}
$("metadataDialog").addEventListener("close",()=>{lookupSeq++;});
$("lookupForm").onsubmit=async e=>{
  e.preventDefault();const seq=++lookupSeq,opts=checkedSources();$("matches").replaceChildren();
  if(!opts.length){$("metaStatus").textContent=tr("Bitte einen Suchanbieter auswählen.");return;}
  $("metaStatus").textContent=tr("Kataloge werden durchsucht …");
  try{
    const r=await api("/web/admin/metadata/search","POST",{term:$("metaTerm").value,sources:opts});
    if(seq!==lookupSeq)return;
    $("metaStatus").textContent=r.matches.length+tr(" Treffer")+(r.unavailable.length?tr(" · Zurzeit nicht erreichbar: ")+r.unavailable.join(", "):"");
    for(const data of r.matches){
      const b=el("button",null,"match");b.type="button";b.append(el("strong",data.title),el("small",[data.author,data.year,sources[data.source]].filter(Boolean).join(" · ")));
      if(data.image){const img=el("img");img.src=data.image;img.referrerPolicy="no-referrer";img.alt="";img.loading="lazy";b.prepend(img);}
      b.onclick=()=>{fillMeta(data);selectCover(data.image);$("coverFile").value="";$("matches").replaceChildren();$("metaStatus").textContent=tr("Treffer übernommen. Angaben prüfen und speichern.");$("field-title").focus();};
      $("matches").append(b);
    }
  }catch(err){if(seq===lookupSeq)$("metaStatus").textContent=err.message;}
};
$("metaForm").onsubmit=async e=>{
  e.preventDefault();const data={source:metaSource};for(const k of Object.keys(metadataFields))data[k]=$("field-"+k).value;
  try{
    const file=$("coverFile").files[0];
    if(file){
      if(file.size>5*1024*1024)throw new Error(tr("Bitte ein Cover bis 5 MB wählen."));
      data.coverData=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(",")[1]);r.onerror=()=>reject(new Error(tr("Cover konnte nicht gelesen werden.")));r.readAsDataURL(file);});
    }else if($("useCover").checked&&coverCandidate)data.coverUrl=coverCandidate;
    data.coverRole=$("coverRole").value;if($("resetCover").checked)data.resetRole=data.coverRole;
    await api("/web/admin/metadata/"+current.id,"POST",data);shelfRevision=String(Date.now());
    if(data.coverData||data.coverUrl){current.cover=true;delete data.coverData;delete data.coverUrl;}
    current.title=data.title;current.authors=data.author?[{name:data.author}]:[];current.metadata=data;
    $("readerTitle").textContent=data.title;$("author").textContent=data.author;configureBook();$("metadataDialog").close();
  }catch(err){$("metaStatus").textContent=err.message;}
};
$("readTags").onclick=async()=>{
  try{fillMeta(await api("/web/admin/metadata/"+current.id));$("metaStatus").textContent=tr("Dateitags ausgelesen. Änderungen mit Speichern bestätigen.");}
  catch(e){$("metaStatus").textContent=e.message;}
};
let feedSeq=0,feedReady="";
function resetFeed(){feedSeq++;feedReady="";$("feedItems").replaceChildren();}
function feedModeUI(){
  const auto=$("feedMode").value==="abo";
  $("retentionInfo").hidden=!auto;$("importGo").textContent=auto?tr("Feed abonnieren"):tr("Gewählte Folgen importieren");
}
$("feedMode").onchange=()=>{resetFeed();feedModeUI();$("importStatus").textContent="";};
$("feedUrl").oninput=()=>{resetFeed();$("importStatus").textContent="";};
async function knownFeeds(){
  const rows=await api("/web/admin/rss/feeds");
  $("knownFeeds").replaceChildren(...rows.map(r=>new Option(r.title,r.feed)));
  const manager=$("feedManager");manager.replaceChildren();
  const subscriptions=rows.filter(r=>r.id);
  if(subscriptions.length)manager.append(el("h3",tr("Abonnierte Feeds")));
  for(const r of subscriptions){
    const row=el("div",null,"feedRow"),label=el("div"),stop=el("button",tr("Abo beenden"));
    label.append(el("strong",r.title),el("small",r.error||(r.checked?tr("Zuletzt geprüft am ")+new Date(r.checked*1000).toLocaleString(uiLanguage):tr("Erster Abruf steht an"))));
    stop.type="button";stop.onclick=async()=>{stop.disabled=true;try{await api("/web/admin/rss/unsubscribe","POST",{id:r.id});await knownFeeds();$("importStatus").textContent=tr("Abo beendet. Die gespeicherten Folgen bleiben in der Bibliothek.");}catch(e){stop.disabled=false;$("importStatus").textContent=e.message;}};
    row.append(label,stop);manager.append(row);
  }
}
$("previewFeed").onclick=async()=>{
  if(!$("feedUrl").reportValidity())return;
  resetFeed();const seq=feedSeq,url=$("feedUrl").value.trim();
  $("importStatus").textContent=tr("Folgen werden geladen …");
  try{
    const r=await api("/web/admin/rss/preview","POST",{url});if(seq!==feedSeq)return;
    feedReady=url;$("importStatus").textContent=r.show+" · "+r.episodes.length+tr(" Folgen");
    const auto=$("feedMode").value==="abo";
    for(const ep of auto?r.episodes.slice(0,5):r.episodes){
      if(auto){$("feedItems").append(el("div",ep.title));continue;}
      const label=el("label",null,"check"),input=el("input");input.type="checkbox";input.value=ep.guid;input.disabled=ep.imported;
      label.append(input,document.createTextNode(ep.title+(ep.imported?tr(" · In der Bibliothek"):"")));$("feedItems").append(label);
    }
  }catch(e){if(seq===feedSeq)$("importStatus").textContent=e.message;}
};
async function importFeed(){
  if($("feedMode").value==="abo"){
    $("importGo").disabled=true;
    try{const r=await api("/web/admin/rss/subscribe","POST",{url:$("feedUrl").value.trim()});$("importDialog").close();await home();message("„"+r.title+tr("“ ist abonniert. Audilege lädt die neuesten Folgen im Hintergrund."));}
    catch(err){$("importStatus").textContent=err.message;}finally{$("importGo").disabled=false;}
    return;
  }
  const selection=Array.from($("feedItems").querySelectorAll("input:checked:not(:disabled)"));
  if(!selection.length||feedReady!==$("feedUrl").value.trim()){$("importStatus").textContent=tr("Bitte den Feed laden und Folgen auswählen.");return;}
  const url=feedReady;$("importGo").disabled=true;$("previewFeed").disabled=true;$("feedUrl").disabled=true;
  try{
    for(let i=0;i<selection.length;i++){
      $("importStatus").textContent=tr("Importiere Folge ")+(i+1)+tr(" von ")+selection.length+" …";
      await api("/web/admin/rss/import","POST",{url,guid:selection[i].value});selection[i].checked=false;selection[i].disabled=true;
    }
    $("importDialog").close();await home();message(selection.length+" Podcastfolge(n) importiert.");
  }catch(e){$("importStatus").textContent=e.message;}finally{$("importGo").disabled=$("previewFeed").disabled=$("feedUrl").disabled=false;}
}

let podcastFilter="",allEpisodes=false;
function openPodcastFolder(key=""){
  shelfPage="library";facetValue="";
  category="podcast";podcastFilter=key;allEpisodes=false;$("bookSearch").value="";renderShelf();
  $("shelfTitle").scrollIntoView({block:"start"});
}
function podcastOverview(shelf,term){
  const shows=subscriptions.filter(s=>(s.show+" "+s.creator).toLocaleLowerCase().includes(term));
  if(term&&!shows.length)return;
  const header=el("div",null,"podHeader"),open=el("button",tr("Podcastordner öffnen →"),"textButton");
  open.onclick=()=>openPodcastFolder();header.append(el("h2","Podcasts"),open);shelf.append(header);
  if(!shows.length){shelf.append(el("p",tr("Keine abonnierten Podcasts."),"muted"));return;}
  const grid=el("div",null,"grid");shelf.append(grid);
  for(const s of (shelfPage==="start"?shows.slice(0,6):shows)){
    const tile=el("button",null,"book podTile");
    const episode=books.filter(b=>b.podcast?.key===s.key&&b.cover).sort((a,b)=>b.id-a.id)[0];
    const fallback=()=>cover(episode||{title:s.show});
    if(s.cover){
      const img=el("img",null,"art");img.alt="";img.onerror=()=>img.replaceWith(fallback());img.src="/web/podcasts/"+s.id+"/cover";tile.append(img);
    }else tile.append(fallback());
    tile.append(el("strong",s.show));if(s.creator&&s.creator!==s.show)tile.append(el("small",s.creator));
    tile.onclick=()=>openPodcastFolder(s.key);grid.append(tile);
  }
}
function podcastShelf(shelf,items,term){
  const groups=new Map(subscriptions.map(s=>[s.key,{...s,count:0}]));
  for(const b of books.filter(b=>b.category==="podcast")){
    const show=b.podcast?.show||b.authors[0]?.name||tr("Ohne Podcastangabe"),key=b.podcast?.key||show;
    if(!groups.has(key))groups.set(key,{key,show,creator:b.podcast?.creator,count:0});
    groups.get(key).count++;
  }
  if(!groups.has(podcastFilter))podcastFilter="";
  const title=b=>b.podcast?.show||b.authors[0]?.name||tr("Ohne Podcastangabe");
  const newest=items.filter(b=>!podcastFilter||(b.podcast?.key||title(b))===podcastFilter).sort(compareBooks);
  const layout=el("div",null,"podLayout"),feed=el("section"),shows=el("section");
  feed.append(el("h3",(podcastFilter?groups.get(podcastFilter).show+" · ":"")+($("shelfSort").value==="new"?tr("Neueste Folgen"):tr("Folgen"))));
  if(!newest.length)feed.append(el("p",term?tr("Keine passenden Folgen gefunden."):tr("Noch keine Folgen vorhanden."),"muted"));
  for(const b of (allEpisodes?newest:newest.slice(0,10))){
    const row=el("button",null,"episodeRow"),text=el("span");
    text.append(el("strong",b.title),el("small",title(b)));
    row.append(cover(b),text);
    if(b.podcast?.published!=null){const d=new Date(b.podcast.published*1000),tag=el("time",d.toLocaleDateString(uiLanguage,{day:"numeric",month:"short",year:"numeric"}));tag.dateTime=d.toISOString();row.append(tag);}
    row.onclick=()=>openReader(b).catch(hint);feed.append(row);
  }
  if(newest.length>10){const more=el("button",allEpisodes?tr("Weniger anzeigen"):tr("Alle Folgen anzeigen"),"textButton");more.onclick=()=>{allEpisodes=!allEpisodes;renderShelf();};feed.append(more);}
  shows.append(el("h3",tr("Nach Podcast")));
  if(podcastFilter){const clear=el("button",tr("Alle Podcasts"),"textButton");clear.onclick=()=>{podcastFilter="";allEpisodes=false;renderShelf();};shows.append(clear);}
  for(const g of [...groups.values()].sort((a,b)=>a.show.localeCompare(b.show,uiLanguage))){
    const b=el("button",null,"showRow");b.setAttribute("aria-pressed",String(podcastFilter===g.key));
    b.append(el("strong",g.show),el("small",[g.creator,g.count+(g.count===1?tr(" Folge"):tr(" Folgen"))].filter(Boolean).join(" · ")));
    b.onclick=()=>{podcastFilter=podcastFilter===g.key?"":g.key;allEpisodes=false;renderShelf();};shows.append(b);
  }
  if(account?.is_admin){const add=el("button",tr("Feed abonnieren"),"textButton");add.onclick=()=>{imports();$("type").value="rss";configure();$("feedUrl").focus();};shows.append(add);}
  layout.append(feed,shows);shelf.append(layout);
}
const navPaths={libraryNav:"M3 4.5c3.4-.9 6.3-.4 9 1.5 2.7-1.9 5.6-2.4 9-1.5v14c-3.4-.9-6.3-.4-9 1.5-2.7-1.9-5.6-2.4-9-1.5z M12 6v14",statsNav:"M4 20h16 M6 16v-4 M12 16V4 M18 16V8",usersNav:"M15 19v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M13 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M16 4a3 3 0 0 1 0 6 M17 13a4 4 0 0 1 3 4v2"};
for(const [id,d] of Object.entries(navPaths)){
  const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg"),path=document.createElementNS(ns,"path");
  svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");path.setAttribute("fill","none");path.setAttribute("stroke","currentColor");path.setAttribute("stroke-linejoin","round");path.setAttribute("stroke-linecap","round");path.setAttribute("d",d);svg.append(path);$(id).prepend(svg);
}
