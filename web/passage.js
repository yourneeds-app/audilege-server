"use strict";
// Keep the original EPUB location on every run of displayed text. The two
// reader modes use the same chapter model and create only local, inert markup.
const passageCache = new WeakMap();
const blockTags = new Set("p div section article blockquote h1 h2 h3 h4 h5 h6 ul ol li pre hr br".split(" "));
const inlineTags = new Set("em strong b i sup sub small ruby rt".split(" "));
let pageRuns = [], currentPassage = null;

function chapterModel(xml, path) {
  const doc = new DOMParser().parseFromString(xml,"application/xml");
  const body = doc.getElementsByTagNameNS("*","body")[0];
  if (!body || doc.getElementsByTagName("parsererror").length) throw Error("EPUB-Abschnitt konnte nicht gelesen werden.");
  const runs = [], anchors = new Map(), locations = new Map();
  let content = "";
  function visit(element, cfi, inherited, sentence) {
    const tag = element.localName.toLowerCase();
    if (["script","style","iframe","object","svg","audio","video"].includes(tag) || element.hasAttribute("hidden")) return null;
    const id = element.getAttribute("id");
    const anchor = id ? path + "#" + id : inherited;
    const types = (element.getAttributeNS("http://www.idpf.org/2007/ops","type") || "").split(/\s+/);
    if (types.includes("storyteller:sentence-span")) sentence = anchor;
    const branch = {tag:blockTags.has(tag)||inlineTags.has(tag)?tag:"span",children:[]};
    locations.set(cfi,content.length);
    if (id) anchors.set(anchor,content.length);
    let children = 0;
    for (const child of element.childNodes) {
      if (child.nodeType === 1) {
        const item = visit(child,cfi+"/"+(++children*2),anchor,sentence);
        if (item) branch.children.push(item);
      } else if (child.nodeType === 3 || child.nodeType === 4) {
        const text = child.nodeValue;
        if (!text || (!text.trim() && /[\r\n]/.test(text) && (child.previousElementSibling===null || blockTags.has(child.previousElementSibling.localName)))) continue;
        const location = cfi + "/" + (children*2+1);
        const run = {text,location,anchor,sentence,start:content.length};
        locations.set(location,content.length);
        content += text; runs.push(run);branch.children.push(run);
      }
    }
    return branch;
  }
  const bodyStep = ([...doc.documentElement.children].indexOf(body)+1)*2;
  const tree = visit(body,"/"+bodyStep,"","");
  return {tree,runs,anchors,locations,content};
}
async function getPassage(pub,index,book) {
  const sec=pub.sections[index];
  if (!sec.path || !["audilege","ebook"].includes(book.category)) return null;
  let task=passageCache.get(sec);
  if (!task) {
    const path=sec.path.split("/").map(encodeURIComponent).join("/");
    task=fetch("/api/v1/epub/"+book.id+"/file/"+path+"?fileId="+pub.fileId).then(async response=>{
      if (!response.ok) throw Error(tr("Abschnitt konnte nicht geladen werden."));
      return chapterModel(await response.text(),sec.path);
    });
    passageCache.set(sec,task);
    task=task.catch(()=>{passageCache.delete(sec);message(tr("Originalformatierung konnte nicht geladen werden. Der Abschnitt wird als Text angezeigt."));return null;});
    passageCache.set(sec,task);
  }
  return task;
}
function passageRun(runs,offset) {
  let lo=0,hi=runs.length;
  while(lo<hi){const mid=(lo+hi)>>>1;if(runs[mid].start<=offset)lo=mid+1;else hi=mid;}
  return runs[Math.max(0,lo-1)];
}
function cfiAt(offset) {
  const run=currentPassage && passageRun(currentPassage.runs,offset);
  return "epubcfi(/"+(publication.spineStep||6)+"/"+(2*(chapter+1))+"!"+
    (run ? run.location+":"+Math.min(run.text.length,Math.max(0,offset-run.start)) : "/4")+")";
}
function fromCfi(model,value) {
  if (!model || !value) return null;
  const match=/!((?:\/\d+(?:\[[^\]]*\])?)+)(?::(\d+))?\)$/.exec(value);
  if (!match) return null;
  const start=model.locations.get(match[1].replace(/\[[^\]]*\]/g,""));
  return start == null ? null : Math.min(model.content.length,start+Number(match[2]||0));
}
function cueAtOffset(offset) {
  if (!currentPassage) return 0;
  let last=0;
  for (const [i,cue] of cues.entries()) {
    const start=currentPassage.anchors.get(cue.anchor);
    if (start==null) continue;
    if(start>offset) break;
    last=i;
  }
  return last;
}
function renderPassage(root,model,paged) {
  const live=[];
  if(!paged){anchorNodes=new Map();sentenceNodes=new Map();activeSpans=[];}
  function build(item) {
    if(item.text===undefined) {
      const node=document.createElement(item.tag);
      for(const child of item.children)node.append(build(child));
      return node;
    }
    const node=document.createTextNode(item.text);live.push({start:item.start,node});
    if(paged || (!item.anchor&&!item.sentence))return node;
    const span=document.createElement("span");span.append(node);
    span.dataset.anchor=item.anchor;span.dataset.sentence=item.sentence;
    for (const [map,key] of [[anchorNodes,item.anchor],[sentenceNodes,item.sentence]]) {
      if(!key)continue;
      if(!map.has(key))map.set(key,[]);
      map.get(key).push(span);
    }
    return span;
  }
  root.replaceChildren(...model.tree.children.map(build));
  if(paged){pageContent=model.content;pageRuns=live;}
  else {
    // Group unaligned word spans with the nearest timed word in their sentence.
    // Never invent timestamps or bridge a sentence boundary.
    const timed=new Set(cues.map(c=>c.anchor));
    for(const group of sentenceNodes.values()){
      let previous=null;const prefix=[];
      for(const span of group){
        const key=span.dataset.anchor;
        if(timed.has(key)){previous=key;if(prefix.length)anchorNodes.get(key).push(...prefix.splice(0));}
        else if(key!==span.dataset.sentence && span.textContent.trim()){
          if(previous)anchorNodes.get(previous).push(span);else prefix.push(span);
        }
      }
    }
    highlight();
  }
}
async function layoutPassage(offset) {
  const pub=publication,index=chapter,mode=readerMode;
  if(!pub)return;
  const model=await getPassage(pub,index,current);
  if(!model || publication!==pub || chapter!==index || readerMode!==mode)return;
  currentPassage=model;
  if(isPaged()) {renderPassage($("pageText"),model,true);positionPage(offset);}
  else if(mode==="along")renderPassage($("text"),model,false);
}
