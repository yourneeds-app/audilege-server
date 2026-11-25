"use strict";
const narrowScreen=matchMedia("(max-width: 760px)");
let discovering=false;
function setDrawer(open){
  $("shell").classList.toggle("drawerOpen",open);
  $("sidebar").inert=!open&&narrowScreen.matches;$("backdrop").hidden=!open||!narrowScreen.matches;
  $("menuToggle").setAttribute("aria-expanded",String(open));
}
function initialDrawer(){setDrawer(!narrowScreen.matches&&localStorage.getItem("audilege-sidebar")!=="closed");}
initialDrawer();narrowScreen.addEventListener("change",initialDrawer);
$("menuToggle").onclick=()=>{
  const open=!$("shell").classList.contains("drawerOpen");
  setDrawer(open);
  if(!narrowScreen.matches)localStorage.setItem("audilege-sidebar",open?"open":"closed");
  else if(open)$("libraryNav").focus();
};
function dismiss(){setDrawer(false);$("menuToggle").focus();}
$("backdrop").onclick=dismiss;
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"&&narrowScreen.matches&&!$("backdrop").hidden)dismiss();
});
function renderSidebarCategories(groups){
  const holder=$("sideCategories");holder.replaceChildren();
  for(const k of groups){
    const button=el("button",categories[k]);button.onclick=async()=>{
      resetShelf();category=k;await home().catch(hint);
    };holder.append(button);
  }
}
$("discoverNav").onclick=()=>{resetShelf();discovering=true;home().catch(hint);};
$("profileNav").onclick=async()=>{await leaveReader();show("profileView");$("profileName").textContent=account.name;$("profileServer").textContent=new URL(".",document.baseURI).href;};
$("settingsNav").onclick=async()=>{await leaveReader();show("settingsView");};
$("shelfSort").value=localStorage.getItem("audilege-sort")||"new";
$("shelfSort").onchange=()=>{localStorage.setItem("audilege-sort",$("shelfSort").value);renderShelf();};
const byName=new Intl.Collator(uiLanguage,{numeric:true,sensitivity:"base"});
function storageLabel(book){
  const names={collection:"Sammlung",inbox:"Medieneingang",library:"Serverbibliothek",source:"Quellordner"};
  const location=book.storage;
  return [tr(names[location?.kind]||"Serverbibliothek"),location?.path].filter(Boolean).join(" / ");
}
function compareOptional(left,right,direction=1){
  if(!left||!right)return Number(!left)-Number(!right);
  return byName.compare(left,right)*direction;
}
function volumeOrder(left,right){
  const volume=value=>{
    const text=String(value??"").trim().replace(",",".");
    return text && Number.isFinite(Number(text)) ? Number(text) : Infinity;
  };
  return volume(left)-volume(right)||compareOptional(String(left??""),String(right??""));
}
function compareBooks(a,b){
  const order=$("shelfSort").value,title=byName.compare(a.title,b.title);
  if(order==="az"||order==="za")return order==="az"?title:-title;
  if(order==="author")return byName.compare(a.authors[0]?.name||"",b.authors[0]?.name||"")||title;
  if(order==="series"||order==="seriesDesc"){
    const left=String(a.metadata?.series||"").trim(),right=String(b.metadata?.series||"").trim();
    return compareOptional(left,right,order==="series"?1:-1)
      ||(left&&right?volumeOrder(a.metadata?.volume,b.metadata?.volume):0)||title||a.id-b.id;
  }
  if(order==="location"||order==="locationDesc"){
    return byName.compare(storageLabel(a),storageLabel(b))*(order==="location"?1:-1)||title||a.id-b.id;
  }
  const direction=order==="old"?1:-1;
  if(a.category==="podcast"&&b.category==="podcast"){
    const left=a.podcast?.published,right=b.podcast?.published;
    if(left!=null&&right!=null&&left!==right)return (left-right)*direction;
    if((left!=null)!==(right!=null))return left==null?1:-1;
  }
  return (a.id-b.id)*direction||title;
}
const prefs={};
function preference(group,key,label,values,initial,apply){
  const select=el("select"),field=el("label",label);
  for(const [value,text] of values)select.add(new Option(text,value));
  const stored=localStorage.getItem("audilege-pref-"+key);
  select.value=values.some(([k])=>k===stored)?stored:initial;
  function update(){prefs[key]=select.value;apply(select.value);}
  select.onchange=()=>{update();localStorage.setItem("audilege-pref-"+key,select.value);
    if(publication&&isPaged())positionPage(pageOffset);
  };
  field.append(select);group.append(field);update();return select;
}
function prefGroup(name){const section=el("section",null,"panel prefGroup");section.append(el("h2",name));$("preferences").append(section);return section;}
const appearance=prefGroup(tr("Darstellung")),readingPrefs=prefGroup(tr("Lesen & Mitlesen")),audioPrefs=prefGroup(tr("Wiedergabe"));
function languageField(){
  const field=el("label",tr("Sprache")),select=el("select");
  for(const [code,name] of [["de","Deutsch"],["en","English"]])select.add(new Option(name,code));
  select.value=uiLanguage;select.onchange=async()=>{if(publication)await queueProgress();localStorage.setItem("audilege-ui-language",select.value);location.reload();};
  field.append(select);return field;
}
appearance.append(languageField());$("loginForm").after(languageField());
const cssVar=(key,value)=>document.documentElement.style.setProperty(key,value);
preference(appearance,"theme",tr("Farbschema"),[["auto","System"],["light",tr("Hell")],["dark",tr("Dunkel")]],"auto",v=>document.documentElement.dataset.theme=v);
preference(readingPrefs,"font",tr("Schrift"),[["serif",tr("Buchschrift")],["sans",tr("Systemschrift")]],"serif",v=>cssVar("--book-font",v==="serif"?"Georgia, serif":"system-ui, sans-serif"));
preference(readingPrefs,"size",tr("Schriftgröße"),[["1",tr("Klein")],["1.15",tr("Mittel")],["1.35",tr("Groß")],["1.6",tr("Sehr groß")]],"1.15",v=>cssVar("--book-size",v+"rem"));
preference(readingPrefs,"leading",tr("Zeilenabstand"),[["1.45",tr("Eng")],["1.7","Normal"],["1.95",tr("Weit")]],"1.7",v=>cssVar("--book-leading",v));
preference(readingPrefs,"margin",tr("Seitenrand"),[["1",tr("Schmal")],["1.5",tr("Mittel")],["2.25",tr("Breit")]],"1.5",v=>cssVar("--book-margin",v+"rem"));
preference(readingPrefs,"flow",tr("Lesedarstellung"),[["page",tr("Blättern")],["scroll",tr("Scrollen")]],"page",v=>document.documentElement.dataset.flow=v);
const markPref=preference(readingPrefs,"mark",tr("Markierung"),[["word",tr("Wort")],["sentence",tr("Satz")]],$("mode").value,v=>{$("mode").value=v;localStorage.setItem("audilege-mark",v);if(publication)highlight();});
$("mode").addEventListener("change",()=>{markPref.value=$("mode").value;localStorage.setItem("audilege-pref-mark",markPref.value);});
const jumps=["5","10","15","30","60"].map(n=>[n,n+" s"]);
function skipPref(key,label,button,direction){
  preference(audioPrefs,key,label,jumps,"15",v=>{
    $(button).textContent=direction<0?"↶ "+v+" s":v+" s ↷";
    $(button).setAttribute("aria-label",v+tr(" Sekunden ")+(direction<0?tr("zurück"):tr("vor")));
    $(button).onclick=()=>skipAudio(direction*Number(v));
  });
}
skipPref("back",tr("Zurückspringen"),"skipBack",-1);skipPref("forward",tr("Vorspringen"),"skipForward",1);
preference(audioPrefs,"rewind",tr("Rücksprung beim Fortsetzen"),[["0",tr("Aus")],["2","2 s"],["5","5 s"],["10","10 s"]],"0",()=>{});
let pausedBook=null;
media.addEventListener("pause",()=>{if(publication&&!loading)pausedBook={pub:publication,chapter,at:Date.now()};});
media.addEventListener("play",()=>{
  const old=pausedBook;pausedBook=null;
  if(old?.pub===publication&&old.chapter===chapter&&Date.now()-old.at>3000&&Number(prefs.rewind)>0)skipAudio(-Number(prefs.rewind));
});
