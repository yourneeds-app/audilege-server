"use strict";
let shelfPage="start",facetValue="",libraryLinks=[];
const facets={series:tr("Reihen"),tags:tr("Genres"),authors:tr("Autoren"),narrator:tr("Sprecher")};
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
function facetLink(field,value,label=value){
  return action(label,()=>catalogPage(field,value),"facetLink");
}
function appendAuthorLinks(container,book){
  book.authors.forEach((author,index)=>{
    if(index)container.append(document.createTextNode(", "));
    container.append(facetLink("authors",author.name));
  });
}
function renderDetailFacets(book){
  $("author").replaceChildren();
  appendAuthorLinks($("author"),book);
  const series=book.metadata?.series;
  $("detailSeries").replaceChildren(...(series?[facetLink("series",series)]:[]));
  $("detailSeries").hidden=!series;
  const narrator=book.metadata?.narrator;
  $("detailNarrator").replaceChildren(...(narrator?[facetLink("narrator",narrator,tr("Gelesen von")+" "+narrator)]:[]));
  $("detailNarrator").hidden=!narrator;
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
  const options=el("div",null,field==="series"?"facetList seriesList":"facetList");box.append(options);
  for(const [value,items] of [...groups].sort((a,b)=>byName.compare(a[0],b[0])).slice(0,limit)){
    const b=action("",()=>catalogPage(field,value));b.append(el("strong",value),el("small",String(items.length)));
    if(field==="series"){
      const representative=items.filter(item=>item.cover).sort((a,b)=>volumeOrder(a.metadata?.volume,b.metadata?.volume))[0];
      if(representative)b.prepend(cover(representative));
      else b.prepend(el("span","▤","seriesPlaceholder"));
    }
    options.append(b);
  }
}
function globalResults(box,term){
  const tokens=fold(term).trim().split(/\s+/),matches=(...parts)=>tokens.every(t=>fold(parts.join(" ")).includes(t));
  let count=0;
  const titles=books.filter(matchesShelfStatus).filter(b=>matches(b.title,...b.authors.map(a=>a.name),b.metadata?.narrator,b.metadata?.series,b.metadata?.tags,b.metadata?.isbn,b.podcast?.show,b.podcast?.creator)).sort(compareBooks);
  for(const [heading,items] of [[tr("Titel"),titles.filter(b=>b.category!=="podcast")],[tr("Podcastfolgen"),titles.filter(b=>b.category==="podcast")]]){
    if(!items.length)continue;count+=items.length;sectionHead(box,heading);const grid=el("div",null,"grid");box.append(grid);appendBookPage(grid,groupEditions(items));
  }
  for(const [field,heading] of Object.entries(facets)){
    const groups=[...collect(field)].filter(([v])=>matches(v));if(!groups.length)continue;
    count+=groups.length;sectionHead(box,heading);groupsInto(box,field,groups);
  }
  const shows=subscriptions.filter(s=>matches(s.show,s.creator));
  if(shows.length){count+=shows.length;sectionHead(box,tr("Sendungen"));for(const s of shows)box.append(action(s.show,()=>{resetShelf();openPodcastFolder(s.key);}));}
  const n=el("p",count?count+tr(" Treffer"):tr("Keine passenden Titel gefunden."),"muted");n.setAttribute("role","status");box.prepend(n);
}
function renderStart(box){
  const recent=books.filter(b=>b.updatedAt && b.readingProgress<100 && !(b.category==="podcast"&&b.played))
    .sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)).slice(0,3);
  const labels={read:[tr("Zuletzt gelesen"),tr("Weiterlesen")],listen:[tr("Zuletzt gehört"),tr("Weiterhören")],along:[tr("Zuletzt mitgelesen"),tr("Weiter mitlesen")]};
  for(const [index,book] of recent.entries()){
    const mode=book.resumeMode,hero=index===0,card=action("",()=>openReader(book,true),hero?"homeFeature":"homeSmall");
    const art=cover(book,mode==="listen"?"audio":"book");
    const info=el("span",null,"homeInfo"),percent=Math.round(book.readingProgress)+" %";
    if(hero){
      const [eyeline,cta]=labels[mode]||[tr("Zuletzt geöffnet"),tr("Fortsetzen")];
      info.append(el("small",eyeline),el("strong",book.title),el("span",book.authors.map(a=>a.name).join(", ")));
      const progress=el("progress");progress.max=100;progress.value=book.readingProgress;progress.setAttribute("aria-label",tr("Fortschritt"));
      const chapter=book.resumeChapter>0?tr("Kapitel {n}").replace("{n}",book.resumeChapter):"";
      info.append(progress,el("small",[chapter,percent].filter(Boolean).join(" · ")),el("span",cta,"homeCTA"));
      card.append(info,art);box.append(card);
      if(art.tagName==="IMG")art.addEventListener("load",()=>{
        const canvas=document.createElement("canvas");canvas.width=canvas.height=8;
        const ctx=canvas.getContext("2d");if(!ctx)return;
        ctx.drawImage(art,0,0,8,8);
        const data=ctx.getImageData(0,0,8,8).data,sums=[0,0,0];let weight=0;
        for(let i=0;i<data.length;i+=4){
          const rgb=[data[i],data[i+1],data[i+2]],w=(1+Math.max(...rgb)-Math.min(...rgb))*data[i+3]/255;
          rgb.forEach((v,k)=>sums[k]+=v*w);weight+=w;
        }
        if(weight)card.style.setProperty("--cover-base","rgb("+sums.map(x=>Math.round(x/weight)).join(",")+")");
      },{once:true});
      if(recent.length>1){sectionHead(box,tr("Auch angefangen"));box.append(el("div",null,"homeStarted"));}
    }else{
      info.append(el("strong",book.title),el("small",[modeLabels[mode],percent].filter(Boolean).join(" · ")));
      card.append(art,info);box.lastElementChild.append(card);
    }
  }
  const newest=groupEditions(books).filter(b=>b.category!=="podcast").sort((a,b)=>(b.addedAt||"").localeCompare(a.addedAt||"")||b.id-a.id).slice(0,3);
  const columns=el("div",null,"homeColumns");
  if(newest.length){
    const shelf=el("section");sectionHead(shelf,tr("Neu im Regal"),()=>catalogPage("library"));
    const tiles=el("div",null,"homeBooks");newest.forEach(b=>tiles.append(bookTile(b)));shelf.append(tiles);columns.append(shelf);
  }
  if(subscriptions.length){
    const podcasts=el("section",null,"homePodcasts");podcastOverview(podcasts,"");columns.append(podcasts);
  }
  if(columns.children.length)box.append(columns);
  if(!box.children.length)box.append(el("p",tr("Deine Bibliothek ist leer.")));
}
function updateSearchVisibility(){
  const librarySearch = shelfPage==="library" && !discovering && !podcastFilter;
  $("globalTools").hidden = $("shelf").hidden || !(shelfPage==="start" || librarySearch);
}
function renderCollection(){
  updateSearchVisibility();
  if ($("globalTools").hidden) $("bookSearch").value="";
  const term=$("bookSearch").value.trim(),box=$("books");
  const sortKey="audilege-sort:"+[shelfPage,category,podcastFilter,facetValue,Boolean(term),discovering].join("/");
  if($("shelfSort").dataset.key!==sortKey){$("shelfSort").dataset.key=sortKey;$("shelfSort").value=localStorage.getItem(sortKey)||(shelfPage==="series"&&facetValue?"series":localStorage.getItem("audilege-sort"))||"new";}
  $("shelfSort").onchange=()=>{localStorage.setItem(sortKey,$("shelfSort").value);renderShelf();};
  const custom=term||shelfPage==="start"||shelfPage in facets||discovering;
  const startPage=shelfPage==="start"&&!term;
  $("shelf").classList.toggle("startPage",startPage);
  $("shelfTitle").hidden=startPage;
  $("startNav").setAttribute("aria-current",shelfPage==="start"&&!term?"page":"false");
  for(const key of Object.keys(facets))$(key+"Nav").setAttribute("aria-current",shelfPage===key&&!term?"page":"false");
  $("libraryNav").setAttribute("aria-current",!custom?"page":"false");
  $("shelfStatus").hidden=shelfPage!=="library"||discovering;
  const seriesDetail=shelfPage==="series"&&Boolean(facetValue);
  $("shelfSort").hidden=!term&&(seriesDetail||shelfPage==="start"||shelfPage in facets&&!facetValue);
  $("showSeries").parentElement.hidden=!term&&(category==="podcast"||shelfPage in facets&&!facetValue);
  if(!custom)return false;
  $("resume").replaceChildren();$("resume").hidden=true;$("categories").replaceChildren();box.replaceChildren();
  renderSidebarCategories(Object.keys(categories).filter(k=>books.some(b=>b.category===k)||(k==="podcast"&&subscriptions.length)));
  $("folderBack").hidden=!term&&(shelfPage==="start"||shelfPage==="library"&&!discovering);
  if(term){$("shelfTitle").textContent=tr("Suchergebnisse");globalResults(box,term);return true;}
  if(shelfPage in facets){
    const groups=collect(shelfPage);$("shelfTitle").textContent=facetValue||facets[shelfPage];
    if(facetValue){
      const items=[...(groups.get(facetValue)||[])];
      items.sort(seriesDetail?(a,b)=>volumeOrder(a.metadata?.volume,b.metadata?.volume)||byName.compare(a.title,b.title):compareBooks);
      const grid=el("div",null,"grid");box.append(grid);appendBookPage(grid,groupEditions(items));
      if(shelfPage==="series")for(const link of libraryLinks.filter(x=>x.kind==="gap"&&items.some(b=>b.id===x.book)))box.append(el("p",tr("Fehlender Band: ")+link.target));
    }else groupsInto(box,shelfPage,groups);
    if(!groups.size)box.append(el("p",tr("Noch keine Einträge vorhanden.")));return true;
  }
  if(discovering){
    $("shelfTitle").textContent=tr("Entdecken");
    const fresh=books.filter(b=>!b.updatedAt&&b.category!=="podcast");
    const next=fresh.filter(b=>b.metadata?.series&&Number(b.metadata.volume)>0&&books.some(p=>p.metadata?.series===b.metadata.series&&p.readingProgress>=99&&Number(p.metadata.volume)+1===Number(b.metadata.volume)));
    for(const [label,items] of [[tr("Zuletzt hinzugefügt"),books.filter(b=>b.category!=="podcast").sort((a,b)=>b.id-a.id).slice(0,6)],[tr("Nächster Band"),next],[tr("Noch nicht begonnen"),fresh.sort(compareBooks)]]){
      if(!items.length)continue;sectionHead(box,label);const grid=el("div",null,"grid");box.append(grid);appendBookPage(grid,groupEditions(items));
    }
    return true;
  }
  renderStart(box);return true;
}

$("shelfStatus").onchange=renderShelf;
$("showSeries").checked=localStorage.getItem("audilege-show-series")==="true";
$("showSeries").onchange=()=>{
  localStorage.setItem("audilege-show-series",String($("showSeries").checked));renderShelf();
};
const globalTools=el("div",null,"globalTools");globalTools.id="globalTools";
const search=$("bookSearch");globalTools.append(search);document.querySelector("main.page").prepend(globalTools);
const navIcons={startNav:[tr("Start"),"⌂"],seriesNav:[tr("Reihen"),"▤"],tagsNav:[tr("Genres"),"◇"],authorsNav:[tr("Autoren"),"♙"],settingsNav:[tr("Einstellungen"),"⚙"],profileNav:[tr("Server & Profil"),"▣"],versionNav:[tr("Info & Updates"),"ⓘ"]};
const start=action(tr("Start"),()=>catalogPage("start"));start.id="startNav";$("libraryNav").before(start);
for(const [key,label] of Object.entries(facets)){const b=action(label,()=>catalogPage(key));b.id=key+"Nav";$("categoryNav").append(b);}
const versionButton=action("",async()=>{await leaveReader();show("settingsView");$("infoPanel").open=true;});versionButton.id="versionNav";$("settingsNav").after(versionButton);
for(const [id,[label,symbol]] of Object.entries(navIcons)){
  const b=$(id);b.title=label;b.setAttribute("aria-label",label);b.dataset.symbol=symbol;
}
for(const b of [$("libraryNav"),$("statsNav"),$("usersNav"),$("discoverNav")]){b.title=b.textContent;b.setAttribute("aria-label",b.textContent);}
search.oninput=()=>{if(!globalTools.hidden)renderShelf();};
document.addEventListener("keydown",e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"&&!$("shell").hidden&&!globalTools.hidden&&!$("mainPage").inert&&!document.querySelector("dialog[open]")){
    e.preventDefault();search.focus();search.select();
  }
  if(e.key==="Escape"&&document.activeElement===search){search.value="";renderShelf();}
});
$("folderBack").onclick=()=>{if(facetValue){facetValue="";renderShelf();}else{resetShelf();renderShelf();}};
