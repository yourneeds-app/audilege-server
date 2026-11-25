"use strict";
let followPassage=true,stopAtChapter=false,sleepTimer=null,speechEpoch=0;
let jumpBack=null;
function rememberJump(){jumpBack={pub:publication,index:chapter,cue:cueIndex,time:within(),offset:pageOffset};}
function resetReadingTools(){
  jumpBack=null;followPassage=true;stopAtChapter=false;clearTimeout(sleepTimer);speechEpoch++;
  if("speechSynthesis" in window)speechSynthesis.cancel();
  window.CSS?.highlights?.delete("voice");
}
const toolsRow=el("div",null,"readerExtras");$("activeBook").prepend(toolsRow);
const paperHeading=el("h2",null,"paperHeading");$("chapterWrap").parentElement.after(paperHeading);
const paperToggle=action(tr("Steuerung"),togglePaper,"paperToggle");paperToggle.hidden=true;toolsRow.before(paperToggle);
function togglePaper(){
  if(publication&&readerMode!=="listen"){
    const quiet=$("reader").classList.toggle("focusPaper");
    paperToggle.hidden=!quiet;paperToggle.setAttribute("aria-expanded",String(!quiet));
  }
}
for(const id of ["pageWindow","text"])$(id).addEventListener("click",e=>{
  if(!getSelection()?.toString()&&Math.abs(e.clientX-innerWidth/2)<innerWidth*.17)togglePaper();
});
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&$("reader").classList.contains("focusPaper")&&!document.querySelector("dialog[open]"))togglePaper();});
const aa=action("Aa",()=>{
  const box=sheet(tr("Leseeinstellungen"));
  for(const label of readingPrefs.querySelectorAll("label")){
    const original=label.querySelector("select"),copy=original.cloneNode(true);copy.value=original.value;
    copy.onchange=()=>{original.value=copy.value;original.dispatchEvent(new Event("change"));};
    box.append(labelControl(label.firstChild.textContent,copy));
  }
});aa.setAttribute("aria-label",tr("Leseeinstellungen"));
preference(readingPrefs,"emphasis",tr("Hervorhebung"),[["fill",tr("Hinterlegen")],["line",tr("Unterstreichen")]],"fill",v=>document.documentElement.dataset.emphasis=v);
preference(readingPrefs,"paper",uiLanguage==="de"?"Papierfarbe":"Page colour",[["auto","System"],["ivory","Sepia"],["white",uiLanguage==="de"?"Weiß":"White"],["night",uiLanguage==="de"?"Nacht":"Night"]],"auto",v=>document.documentElement.dataset.paper=v);
const returnToAudio=action(tr("Zur Hörstelle"),()=>{followPassage=true;activeSpans[0]?.scrollIntoView({block:"center"});returnToAudio.hidden=true;});returnToAudio.hidden=true;
const readerMenu=el("details");readerMenu.append(el("summary",tr("Werkzeuge")));
toolsRow.append(aa,returnToAudio,readerMenu);
const players=(data)=>api("web/player",data?"POST":"GET",data);
function readerControls(){
  paperToggle.hidden=true;
  const textual=current&&["ebook","audilege"].includes(current.category);
  aa.hidden=!textual||readerMode==="listen";returnToAudio.hidden=readerMode!=="along"||followPassage;
  readerMenu.open=false;
  readerMenu.replaceChildren(el("summary",tr("Werkzeuge")));
  if(textual)readerMenu.append(action(tr("Im Buch suchen"),findInBook));
  readerMenu.append(action(tr("Lesezeichen"),bookmarkSheet));
  const undo=action(tr("Rückgängig"),async()=>{
    if(jumpBack?.pub!==publication)return;
    const j=jumpBack;jumpBack=null;await locate(j.index,j.offset,j.cue,false);
    if(!isPaged()&&j.cue>=0){setCue(j.cue,j.time);dirty=true;await queueProgress();}
  });
  readerMenu.ontoggle=()=>{undo.hidden=jumpBack?.pub!==publication;};
  undo.hidden=!jumpBack;readerMenu.append(undo);
  if(!isPaged())readerMenu.append(action(tr("Sleep-Timer"),timerSheet));
  if(!isPaged()&&(navigator.mediaDevices?.selectAudioOutput||media.webkitShowPlaybackTargetPicker||media.remote))readerMenu.append(action(tr("Wiedergabegerät"),async()=>{
    if(navigator.mediaDevices?.selectAudioOutput&&media.setSinkId){const output=await navigator.mediaDevices.selectAudioOutput();await media.setSinkId(output.deviceId);}
    else if(media.webkitShowPlaybackTargetPicker)media.webkitShowPlaybackTargetPicker();else await media.remote.prompt();
  }));
  if(textual&&isPaged()&&"speechSynthesis" in window)readerMenu.append(action(tr("Text vorlesen"),speakPassage));
}
function pauseFollowing(){if(readerMode==="along"&&publication){followPassage=false;returnToAudio.hidden=false;}}
$("text").addEventListener("wheel",pauseFollowing,{passive:true});$("text").addEventListener("touchmove",pauseFollowing,{passive:true});
document.addEventListener("keydown",e=>{if(["PageUp","PageDown","ArrowUp","ArrowDown"].includes(e.key)&&!document.querySelector("dialog[open]"))pauseFollowing();});
function timerSheet(){
  const box=sheet(tr("Sleep-Timer"));
  for(const [v,label] of [[0,tr("Aus")],[-1,tr("Kapitelende")],[10,"10 min"],[20,"20 min"],[30,"30 min"],[60,"60 min"]]){
    box.append(tool(label,()=>{clearTimeout(sleepTimer);stopAtChapter=v===-1;if(v>0)sleepTimer=setTimeout(()=>media.pause(),v*60000);studio.close();}));
  }
}
async function locate(index,offset,cue=-1,remember=true){
  if(remember)rememberJump();
  const pub=publication,b=current;setChapter(index);const model=await getPassage(pub,index,b);if(pub!==publication||index!==chapter)return;
  currentPassage=model;
  if(isPaged()){syncMode(offset);positionPage(offset);}
  else if(cues.length){setCue(cue>=0?Math.min(cue,cues.length-1):cueAtOffset(offset));}
  dirty=true;await queueProgress();
}
function findInBook(){
  const box=sheet(tr("Im Buch suchen")),q=input("search"),list=el("div",null,"studioRows");box.append(labelControl(tr("Suchbegriff"),q),tool(tr("Suchen"),async()=>{
    const term=q.value.trim().toLocaleLowerCase();list.replaceChildren();if(!term)return;
    const pub=publication,b=current;let count=0;
    for(let i=0;i<pub.sections.length&&count<100;i++){
      const m=await getPassage(pub,i,b);if(!studio.open||!list.isConnected||pub!==publication)return;
      const original=m?.content||"",text=original.toLocaleLowerCase();
      for(let off=text.indexOf(term);off!==-1&&count<100;off=text.indexOf(term,off+term.length)){
        const dest=off;count++;list.append(tool(pub.sections[i].name+" · "+original.slice(Math.max(0,off-25),off+term.length+48),async()=>{studio.close();await locate(i,dest);}));
      }
    }
    studioNote.textContent=count+" "+tr("Treffer");
  }),list);q.focus();
}
async function bookmarkSheet(){
  const state=await players(),box=sheet(tr("Lesezeichen")),file=publication.fileId;
  box.append(tool(tr("Stelle merken"),async()=>{
    const offset=isPaged()?pageOffset:(currentPassage?.anchors.get(cues[cueIndex]?.anchor)||0);
    await players({kind:"bookmark",book:current.id,edition:file,chapter,offset,cue:isPaged()?-1:cueIndex,label:currentPassage?.content.slice(offset,offset+90)||section().name});await bookmarkSheet();
  }));
  for(const m of state.marks.filter(m=>m.book===current.id)){
    const pick=tool(m.label,async()=>{studio.close();await locate(m.chapter,m.offset,m.cue);});pick.disabled=m.edition!==file;
    box.append(line(pick,tool(tr("Entfernen"),async()=>{await players({book:current.id,kind:"bookmark",remove:m.id});await bookmarkSheet();})));
  }
}
async function queueSheet(){
  const state=await players(),box=sheet(tr("Als Nächstes"));
  for(const i of state.items.filter(i=>i.kind==="queue")){
    const book=books.find(b=>b.id===i.book);if(!book)continue;
    box.append(line(tool(book.title,async()=>{studio.close();await openReader(book,true,"listen");}),
      tool(tr("Nach vorn"),async()=>{await players({kind:"promote",book:book.id});await queueSheet();}),
      tool(tr("Entfernen"),async()=>{await players({kind:"queue",book:book.id,remove:true});await queueSheet();})));
  }
  if(!box.children.length)box.append(el("p",tr("Die Warteschlange ist leer.")));
}
async function advanceQueue(){
  if(!current)return;const old=current;
  const state=await players({kind:"queue",book:old.id,remove:true});if(old!==current)return;
  const id=state.items.find(i=>i.kind==="queue")?.book,b=books.find(b=>b.id===id);
  if(b){await openReader(b,true,"listen");await media.play();}
}
const queueNav=action(tr("Als Nächstes"),queueSheet);queueNav.dataset.symbol="☷";queueNav.setAttribute("aria-label",tr("Als Nächstes"));queueNav.title=tr("Als Nächstes");$("statsNav").before(queueNav);
const options=$("reader").querySelector(".more div");
const enqueueButton=action(tr("Zu „Als Nächstes“ hinzufügen"),async()=>{await players({book:current.id,kind:"queue"});await queueSheet();});
const playedButton=action(tr("Gespielt / Ungespielt"),async()=>{
  const id=current.id,state=await players(),played=state.items.some(x=>x.kind==="played"&&x.book===id),box=sheet(tr("Wiedergabestatus"));
  box.append(tool(played?tr("Als ungespielt markieren"):tr("Als gespielt markieren"),async()=>{await players({book:id,kind:"played",remove:played});studio.close();await refresh();}));
});
options.append(enqueueButton,playedButton);
function speakPassage(){
  const box=sheet(tr("Text vorlesen"));
  if(!currentPassage){box.append(el("p",tr("Kein lesbarer Abschnitt verfügbar.")));return;}
  const start=tool(tr("Ab dieser Stelle vorlesen"),()=>{studio.close();speechEpoch++;speechSynthesis.cancel();const epoch=speechEpoch,model=currentPassage;
    const lang=publication.language||document.documentElement.lang;
    const remaining=model.content.slice(pageOffset),base=pageOffset;
    const sentences=globalThis.Intl?.Segmenter?[...new Intl.Segmenter(lang,{granularity:"sentence"}).segment(remaining)].map(s=>[s.index,s.segment]):[[0,remaining]];
    function utter(i){
      if(epoch!==speechEpoch||model!==currentPassage||!sentences[i])return;
      const [at,text]=sentences[i],u=new SpeechSynthesisUtterance(text);u.lang=lang;
      function mark(pos,len){
        positionPage(pos);
        if(!window.CSS?.highlights)return;
        const a=passageRun(pageRuns,pos),end=Math.min(model.content.length,pos+len),b=passageRun(pageRuns,end);
        if(!a||!b)return;const r=new Range();r.setStart(a.node,Math.min(a.node.length,pos-a.start));r.setEnd(b.node,Math.min(b.node.length,end-b.start));CSS.highlights.set("voice",new Highlight(r));
      }
      u.onstart=()=>{finishReadSession();startReadSession("tts");mark(base+at,text.length);};
      u.onboundary=e=>{if(epoch===speechEpoch&&e.name==="word"&&$("mode").value==="word")mark(base+at+e.charIndex,e.charLength||text.slice(e.charIndex).match(/^\S+/)?.[0].length||1);};
      u.onend=()=>{if(epoch!==speechEpoch)return;dirty=true;queueProgress();if(i+1<sentences.length)utter(i+1);else{window.CSS?.highlights?.delete("voice");finishReadSession();startReadSession("read");}};
      speechSynthesis.speak(u);
    }utter(0);
  });
  box.append(line(start,tool(tr("Stoppen"),()=>{speechEpoch++;speechSynthesis.cancel();window.CSS?.highlights?.delete("voice");finishReadSession();startReadSession("read");studio.close();})));
}
