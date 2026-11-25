"use strict";
let shelfPage="start",facetValue="",libraryLinks=[];
const facets={series:tr("Reihen"),tags:tr("Genres"),authors:tr("Autoren")};
function action(label,callback,cls=""){
  const b=el("button",label,cls);b.type="button";
  b.onclick=()=>Promise.resolve().then(callback).catch(hint);return b;
}
function labelControl(title,control){const label=el("label",title);label.append(control);return label;}
function choices(pairs,selected){
  const select=el("select");for(const [value,label] of pairs)select.add(new Option(label,value));select.value=selected;return select;
}
function catalogPage(name,value=""){
  resetShelf();shelfPage=name;facetValue=value;return home();
}
function appendBookPage(grid,list,offset=0){
  for(const b of list.slice(offset,offset+48))grid.append(bookTile(b));
  if(list.length>offset+48){const next=action(tr("Weitere Titel anzeigen"),()=>{next.remove();appendBookPage(grid,list,offset+48);});grid.append(next);}
}
function sectionHead(box,title,more){
  const header=el("div",null,"sectionHeading");header.append(el("h2",title));
  if(more)header.append(action(tr("Alle anzeigen"),more,"textButton"));box.append(header);
}
function values(b,field){
  if(field==="authors")return b.authors.map(a=>a.name);
  return String(b.metadata?.[field]||"").split(field==="tags"?/[,;|]/:/[;]/).map(x=>x.trim()).filter(Boolean);
}
function fold(s){return String(s??"").normalize("NFKD").toLocaleLowerCase().replace(/[\u0300-\u036f]/g,"").replace(/ø/g,"o").replace(/ß/g,"ss");}
function collect(field){
  const groups=new Map();
  for(const b of books.filter(b=>b.category!=="podcast"))for(const value of new Set(values(b,field))){
    if(!groups.has(value))groups.set(value,[]);groups.get(value).push(b);
  }
  return groups;
}
function groupsInto(box,field,groups,limit=Infinity){
  const options=el("div",null,"facetList");box.append(options);
  for(const [value,items] of [...groups].sort((a,b)=>byName.compare(a[0],b[0])).slice(0,limit)){
    const b=action("",()=>catalogPage(field,value));b.append(el("strong",value),el("small",String(items.length)));
    if(field==="series")b.prepend(cover(items[0]));options.append(b);
  }
}
function globalResults(box,term){
  const tokens=fold(term).trim().split(/\s+/),matches=(...parts)=>tokens.every(t=>fold(parts.join(" ")).includes(t));
  let count=0;
  const titles=books.filter(b=>matches(b.title,...b.authors.map(a=>a.name),b.metadata?.series,b.metadata?.tags,b.metadata?.isbn,b.podcast?.show,b.podcast?.creator)).sort(compareBooks);
  for(const [heading,items] of [[tr("Titel"),titles.filter(b=>b.category!=="podcast")],[tr("Podcastfolgen"),titles.filter(b=>b.category==="podcast")]]){
    if(!items.length)continue;count+=items.length;sectionHead(box,heading);const grid=el("div",null,"grid");box.append(grid);appendBookPage(grid,items);
  }
  for(const [field,heading] of Object.entries(facets)){
    const groups=[...collect(field)].filter(([v])=>matches(v));if(!groups.length)continue;
    count+=groups.length;sectionHead(box,heading);groupsInto(box,field,groups);
  }
  const shows=subscriptions.filter(s=>matches(s.show,s.creator));
  if(shows.length){count+=shows.length;sectionHead(box,tr("Sendungen"));for(const s of shows)box.append(action(s.show,()=>{resetShelf();openPodcastFolder(s.key);}));}
  const n=el("p",count?count+tr(" Treffer"):tr("Keine passenden Titel gefunden."),"muted");n.setAttribute("role","status");box.prepend(n);
}
function renderCollection(){
  const term=$("bookSearch").value.trim(),box=$("books");
  const sortKey="audilege-sort:"+[shelfPage,category,podcastFilter,facetValue,Boolean(term),discovering].join("/");
  if($("shelfSort").dataset.key!==sortKey){$("shelfSort").dataset.key=sortKey;$("shelfSort").value=localStorage.getItem(sortKey)||localStorage.getItem("audilege-sort")||"new";}
  $("shelfSort").onchange=()=>{localStorage.setItem(sortKey,$("shelfSort").value);renderShelf();};
  const custom=term||shelfPage==="start"||shelfPage in facets||discovering;
  $("startNav").setAttribute("aria-current",shelfPage==="start"&&!term?"page":"false");
  for(const key of Object.keys(facets))$(key+"Nav").setAttribute("aria-current",shelfPage===key&&!term?"page":"false");
  $("libraryNav").setAttribute("aria-current",!custom?"page":"false");
  $("shelfSort").hidden=!term&&(shelfPage==="start"||shelfPage in facets&&!facetValue);
  if(!custom)return false;
  $("resume").replaceChildren();$("resume").hidden=true;$("categories").replaceChildren();box.replaceChildren();
  renderSidebarCategories(Object.keys(categories).filter(k=>books.some(b=>b.category===k)||(k==="podcast"&&subscriptions.length)));
  $("folderBack").hidden=!term&&(shelfPage==="start"||shelfPage==="library"&&!discovering);
  if(term){$("shelfTitle").textContent=tr("Suchergebnisse");globalResults(box,term);return true;}
  if(shelfPage in facets){
    const groups=collect(shelfPage);$("shelfTitle").textContent=facetValue||facets[shelfPage];
    if(facetValue){
      const items=[...(groups.get(facetValue)||[])];
      items.sort((a,b)=>shelfPage==="series"&&$("shelfSort").value==="new"?(Number(a.metadata.volume||Infinity)-Number(b.metadata.volume||Infinity)||compareBooks(a,b)):compareBooks(a,b));
      const grid=el("div",null,"grid");box.append(grid);appendBookPage(grid,items);
      if(shelfPage==="series")for(const link of libraryLinks.filter(x=>x.kind==="gap"&&items.some(b=>b.id===x.book)))box.append(el("p",tr("Fehlender Band: ")+link.target));
    }else groupsInto(box,shelfPage,groups);
    if(!groups.size)box.append(el("p",tr("Noch keine Einträge vorhanden.")));return true;
  }
  if(discovering){
    $("shelfTitle").textContent=tr("Entdecken");
    const fresh=books.filter(b=>!b.updatedAt&&b.category!=="podcast");
    const next=fresh.filter(b=>b.metadata?.series&&Number(b.metadata.volume)>0&&books.some(p=>p.metadata?.series===b.metadata.series&&p.readingProgress>=99&&Number(p.metadata.volume)+1===Number(b.metadata.volume)));
    for(const [label,items] of [[tr("Zuletzt hinzugefügt"),books.filter(b=>b.category!=="podcast").sort((a,b)=>b.id-a.id).slice(0,6)],[tr("Nächster Band"),next],[tr("Noch nicht begonnen"),fresh.sort(compareBooks)]]){
      if(!items.length)continue;sectionHead(box,label);const grid=el("div",null,"grid");box.append(grid);appendBookPage(grid,items);
    }
    return true;
  }
  $("shelfTitle").textContent=tr("Übersicht");
  const recent=books.filter(b=>b.updatedAt&&b.readingProgress<100).sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)).slice(0,3);
  if(recent.length){sectionHead(box,tr("Fortsetzen"));const row=el("div",null,"resumeRow");box.append(row);
    for(const b of recent){const card=action("",()=>openReader(b,true),"resumeCard"),t=el("span",null,"resumeText");
      t.append(el("small",categories[b.category]),el("strong",b.title),el("span",b.authors.map(v=>v.name).join(", ")),el("small",Math.round(b.readingProgress)+" %"));
      card.append(cover(b),t);row.append(card);}
  }
  for(const k of ["audilege","ebook","audio"]){
    const list=books.filter(b=>b.category===k).sort((a,b)=>b.id-a.id);if(!list.length)continue;
    sectionHead(box,categories[k],()=>{resetShelf();category=k;return home();});const grid=el("div",null,"grid homeShelf");box.append(grid);
    for(const b of list.slice(0,6))grid.append(bookTile(b));
  }
  if(subscriptions.length)podcastOverview(box,"");
  for(const field of ["series","tags"]){const groups=collect(field);if(groups.size){sectionHead(box,facets[field],()=>catalogPage(field));groupsInto(box,field,groups,6);}}
  if(!box.children.length)box.append(el("p",tr("Deine Bibliothek ist leer.")));return true;
}

const globalTools=el("div",null,"globalTools");globalTools.id="globalTools";
const search=$("bookSearch");globalTools.append(search);document.querySelector("main.page").prepend(globalTools);
const navIcons={startNav:[tr("Start"),"⌂"],seriesNav:[tr("Reihen"),"▤"],tagsNav:[tr("Genres"),"◇"],authorsNav:[tr("Autoren"),"♙"],settingsNav:[tr("Einstellungen"),"⚙"],profileNav:[tr("Server & Profil"),"▣"],versionNav:[tr("Info & Updates"),"ⓘ"]};
const start=action(tr("Start"),()=>catalogPage("start"));start.id="startNav";$("libraryNav").before(start);
for(const [key,label] of Object.entries(facets)){const b=action(label,()=>catalogPage(key));b.id=key+"Nav";$("categoryNav").append(b);}
const versionButton=action("",async()=>{await closeReader();show("settingsView");$("infoPanel").open=true;});versionButton.id="versionNav";$("settingsNav").after(versionButton);
for(const [id,[label,symbol]] of Object.entries(navIcons)){
  const b=$(id);b.title=label;b.setAttribute("aria-label",label);b.dataset.symbol=symbol;
}
for(const b of [$("libraryNav"),$("statsNav"),$("usersNav"),$("discoverNav")]){b.title=b.textContent;b.setAttribute("aria-label",b.textContent);}
$("bookSearch").oninput=()=>{if($("shelf").hidden){show("shelf");}renderShelf();};
document.addEventListener("keydown",e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"&&!$("shell").hidden&&!document.querySelector("dialog[open]")){
    e.preventDefault();(async()=>{if($("shelf").hidden){await closeReader();show("shelf");}search.focus();search.select();})().catch(hint);
  }
  if(e.key==="Escape"&&document.activeElement===search){search.value="";renderShelf();}
});
$("folderBack").onclick=()=>{if(facetValue){facetValue="";renderShelf();}else{resetShelf();renderShelf();}};
