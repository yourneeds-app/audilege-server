"use strict";
const studio=el("dialog");studio.id="studio";document.body.append(studio);
const studioTitle=el("h2"),studioBody=el("div"),studioNote=el("p");studioNote.setAttribute("role","status");
studio.append(studioTitle,studioBody,studioNote,action(tr("Schließen"),()=>studio.close()));
function sheet(title,wide=false){studio.classList.toggle("libraryReview",wide);studioTitle.textContent=title;studioNote.textContent="";studioBody.replaceChildren();if(!studio.open)studio.showModal();return studioBody;}
function tool(label,fn,cls=""){
  const b=action(label,async()=>{b.disabled=true;try{await fn();}catch(e){studioNote.textContent=e.message;}finally{b.disabled=false;}},cls);return b;
}
function input(type="text",value=""){const n=el("input");n.type=type;n.value=value;return n;}
function check(text,checked=false){const n=input("checkbox");n.checked=checked;const l=el("label",null,"check");l.append(n,document.createTextNode(text));return [l,n];}
function line(...children){const row=el("div",null,"toolrow");row.append(...children);return row;}
const role=choices([["book",tr("Buchcover")],["audio",tr("Audiocover")]],"book");role.id="coverRole";
const [resetLabel,resetInput]=check(tr("Eingebettetes Cover wiederherstellen"));resetInput.id="resetCover";
document.querySelector(".coverEditor").append(labelControl(tr("Verwendung"),role),resetLabel);
const adminMenu=el("div",null,"adminActions");$("users").querySelector("header").after(adminMenu);
adminMenu.append(action(tr("Bibliothek prüfen"),aiStudio),action(tr("Speicher & System"),systemStudio));
function jobTimes(job){
  if(job.state!=="running"||!job.started_at)return "";
  const now=Date.now()/1000;
  const labels=[tr("Läuft seit {time}").replace("{time}",clock(now-job.started_at))];
  if(job.phase_at && job.note)labels.push(tr("Aktuelle Phase seit {time}").replace("{time}",clock(now-job.phase_at)));
  return labels.join(" · ");
}
async function adminJobs(){
  const box=el("div"),container=sheet(tr("Aufträge"));container.append(box);
  async function refreshJobs(){
    const result=await api("web/admin/jobs");
    if(!studio.open||!box.isConnected)return;
    box.replaceChildren();
    if(!result.jobs.length)box.append(el("p",tr("Noch keine Einträge vorhanden.")));
    for(const j of result.jobs){
      const row=el("section"),status={done:"Abgeschlossen",running:"Prüfung läuft",waiting:"In Warteschlange",failed:"Prüfung unterbrochen"};
      row.append(el("strong",j.title),el("p",tr(j.note||status[j.state])));
      const times=jobTimes(j);if(times)row.append(el("small",times));
      if(j.state==="failed")row.append(tool(tr("Erneut versuchen"),async()=>{await api("web/admin/jobs/"+j.id+"/retry","POST",{});await adminJobs();}));
      box.append(row);
    }
    if(result.jobs.some(j=>j.state==="waiting"||j.state==="running"))
      setTimeout(()=>{if(studio.open&&box.isConnected)refreshJobs().catch(e=>studioNote.textContent=e.message);},4000);
  }
  await refreshJobs();
}
adminMenu.append(action(tr("Aufträge"),adminJobs));
const aiApi=(path,d)=>api("web/admin/ai/"+path,d===undefined?"GET":"POST",d);
let reviewPoll;
studio.addEventListener("close",()=>{if(!studio.open){clearTimeout(reviewPoll);studioBody.replaceChildren();}});
async function aiStudio(){
  const s=await aiApi("state"),box=sheet(tr("Bibliothek prüfen"),true),cfg=s.config;
  box.append(tool(tr("KI-Anbieter & Modell"),()=>aiSettings(s)));
  const scope=choices([["",tr("Gesamte Bibliothek")],...Object.entries(categories).filter(([k])=>books.some(b=>b.category===k)),...books.map(b=>[String(b.id),b.title])],"");
  box.append(labelControl(tr("Umfang"),scope));
  const [changedLabel,changed]=check(uiLanguage==="de"?"Neue und geänderte Titel":"New and changed titles",true);box.append(changedLabel);
  const options=el("div",null,"reviewChecks");box.append(options);
  const [autoLabel,autoApply]=check(tr("Eindeutige Ergänzungen automatisch übernehmen"),true);box.append(autoLabel);
  const checks=Object.entries(s.checks).filter(([key])=>cfg.enabled||["metadata","series","names"].includes(key)).map(([key,title])=>{const [l,n]=check(tr(title),true);n.value=key;options.append(l);return n;});
  const run=tool(tr("Prüfung starten"),async()=>{await aiApi("run",{book:/^\d+$/.test(scope.value)?scope.value:null,category:scope.value in categories?scope.value:null,changed:changed.checked,autoApply:autoApply.checked,checks:checks.filter(n=>n.checked).map(n=>n.value)});await aiStudio();},"primary");
  box.append(run);
  const active=s.jobs.find(r=>r.state==="running");
  if(s.jobs.length){const j=s.jobs[0];box.append(el("p",({running:tr("Prüfung läuft"),done:tr("Prüfung abgeschlossen"),failed:tr("Prüfung unterbrochen")}[j.state])+" · "+j.note));}
  if(active){run.disabled=true;reviewPoll=setTimeout(()=>{if(studio.open&&studioTitle.textContent===tr("Bibliothek prüfen"))aiStudio().catch(hint);},5000);}
  const list=el("div",null,"studioRows");box.append(list);
  const history=el("details"),appliedList=el("div",null,"studioRows");
  const applied=s.suggestions.filter(p=>p.state==="applied").length;
  if(applied){history.append(el("summary",tr("Übernommene Änderungen")+" · "+applied),appliedList);box.append(history);}
  for(const p of s.suggestions){
    const row=el("article"),current=el("small",tr(p.evidence)),value=input("text",p.new);row.append(el("h3",p.title),el("p",tr(s.checks[p.kind])+" · "+p.field),el("p",p.reason),current);
    const mutable=["metadata","series","names"].includes(p.kind);
    if(mutable){row.append(el("p",tr("Bisher: ")+(p.old||"—")),labelControl(tr("Vorschlag"),value));value.disabled=p.state!=="pending";}
    else if(p.kind==="cover"){
      const old=cover(books.find(b=>b.id===p.book),p.field),candidate=el("img");candidate.src=p.new;candidate.alt=tr("Covervorschlag");candidate.referrerPolicy="no-referrer";row.append(line(old,candidate));
    }else row.append(el("p",books.find(b=>String(b.id)===p.new)?.title||p.new));
    const decide=async action=>{await aiApi("review",{action,id:p.id,value:value.value});await refresh();await aiStudio();};
    row.append(p.state==="applied"?tool(tr("Rückgängig"),()=>decide("undo")):line(tool(tr("Übernehmen"),()=>decide("approve")),tool(tr("Verwerfen"),()=>decide("reject"))));(p.state==="applied"?appliedList:list).append(row);
  }
}
async function aiSettings(s){
  clearTimeout(reviewPoll);const box=sheet(tr("KI-Anbieter & Modell")),c=s.config;
  const provider=choices(Object.entries(s.providers),c.provider),endpoint=input("url",c.endpoint),model=input("text",c.model),key=input("password");
  key.autocomplete="new-password";const [enabled,n]=check(tr("KI-Prüfungen aktivieren"),c.enabled);
  const [clear,clearKey]=check(tr("Gespeicherten Schlüssel entfernen"));box.append(enabled,labelControl(tr("Anbieter"),provider),labelControl(tr("Serveradresse"),endpoint),labelControl(tr("API-Schlüssel"),key),clear,labelControl(tr("Modell"),model));
  const models=el("datalist");models.id="availableModels";model.setAttribute("list",models.id);box.append(models);
  const defaults={openai:"https://api.openai.com/v1",anthropic:"https://api.anthropic.com/v1",gemini:"https://generativelanguage.googleapis.com/v1beta",ollama:"http://127.0.0.1:11434",compatible:""};
  function controls(){endpoint.disabled=!["ollama","compatible"].includes(provider.value);}
  provider.onchange=()=>{endpoint.value=defaults[provider.value];model.value="";key.value="";models.replaceChildren();controls();};controls();
  box.append(el("h3",tr("Kataloge zum Abgleich")));const sources=Object.entries(windowSources()).map(([k,title])=>{const [l,i]=check(title,c.sources.includes(k));box.append(l);return [k,i];});
  const [importsLabel,imports]=check(tr("Neue Buchimporte automatisch prüfen"),!!c.autoImports);box.append(importsLabel);
  const store=()=>aiApi("settings",{enabled:n.checked,autoImports:imports.checked,provider:provider.value,endpoint:endpoint.value,model:model.value,key:key.value,clearKey:clearKey.checked,sources:sources.filter(v=>v[1].checked).map(v=>v[0])});
  box.append(line(tool(tr("Speichern & Modelle laden"),async()=>{await store();key.value="";clearKey.checked=false;const r=await aiApi("models",{});models.replaceChildren(...r.models.map(m=>new Option(m,m)));studioNote.textContent=r.models.length+tr(" Modelle");model.focus();}),tool(tr("Speichern"),async()=>{await store();await aiStudio();},"primary")));
}
function windowSources(){return sources;}
async function folderPicker(path="",linked=false){
  const r=await api("web/admin/directories?path="+encodeURIComponent(path)),box=sheet(tr("Medienordner wählen"));
  box.append(el("p",r.path||tr("Laufwerke")));
  if(r.path)box.append(el("small",new Intl.NumberFormat(uiLanguage,{maximumFractionDigits:1}).format(r.free/1073741824)+(uiLanguage==="de"?" GB frei":" GB available")),
    line(tool(tr("Übergeordneter Ordner"),()=>folderPicker(r.parent,linked)),tool(tr("Diesen Ordner wählen"),async()=>{
      const before=await api("web/admin/inbox");
      const previous=linked?before.linkedFolder:before.folder;
      if(r.path!==previous&&!confirm(previous+" → "+r.path+"\n"+(uiLanguage==="de"?"Neue Dateien hier automatisch einlesen?":"Automatically scan new files here?")))return;
      await api("web/admin/inbox","POST",linked?{linkedFolder:r.path}:{folder:r.path});studio.close();await inboxStatus();})));
  for(const folder of r.folders)box.append(tool(folder.split(/[\\/]/).filter(Boolean).at(-1)||folder,()=>folderPicker(folder,linked)));
}
$("linkedBrowse").onclick=()=>folderPicker("",true).catch(hint);
$("linkedStop").onclick=async()=>{
  try{await api("web/admin/inbox","POST",{linkedFolder:""});await inboxStatus();}catch(err){hint(err);}
};
$("folderDetails").append(action(tr("Ordner durchsuchen"),()=>folderPicker()));
async function systemStudio(){
  const s=await api("web/admin/system"),box=sheet(tr("Speicher & System"));box.append(el("h3",tr("Mitlesefassungen")));
  if(!s.retention.length)box.append(el("p",tr("Keine offenen Speicherentscheidungen.")));
  for(const r of s.retention){
    const row=el("section");row.append(el("strong",r.title));
    const change=async(action,confirmed=false)=>{await api("web/admin/retention","POST",{job:r.job,action,confirmed});await systemStudio();};
    if(["pending","keep","restore"].includes(r.decision))row.append(line(r.decision==="pending"?tool(tr("Alle Dateien behalten"),()=>change("keep")):el("small",tr("Originale erhalten")),tool(tr("Nur Mitlesefassung behalten …"),async()=>{
      const p=await api("web/admin/retention","POST",{job:r.job,action:"preview"}),view=sheet(tr("Originale in den Papierkorb verschieben"));
      for(const f of p.files)view.append(el("p",f.name+" · "+f.path+" · "+Math.ceil(f.bytes/1048576)+" MB"));
      view.append(line(tool(tr("Abbrechen"),systemStudio),tool(tr("In Papierkorb verschieben"),()=>change("trash",true))));
    })));else if(r.decision==="trash")row.append(line(tool(tr("Originale wiederherstellen"),()=>change("restore")),tool(uiLanguage==="de"?"Endgültig löschen":"Delete permanently",async()=>{
      if(confirm(r.title+"\n"+(uiLanguage==="de"?"Die Originale im Papierkorb endgültig löschen?":"Permanently delete the original files in the trash?")))await change("purge",true);
    })));else row.append(el("small",r.decision==="purge"?(uiLanguage==="de"?"Originale gelöscht":"Originals deleted"):tr("Originale erhalten")));
    box.append(row);
  }
  box.append(el("h3",tr("Sicherung & Wiederherstellung")),el("p",tr("Bei beendetem Server: AudilegeServer.exe --backup ZIELORDNER oder --restore SICHERUNG. Eine Wiederherstellung bewahrt den vorherigen Bestand separat auf.")));
  box.append(tool(tr("Nach Updates suchen"),async()=>{const v=await api("web/admin/updates");const a=el("a","GitHub-Releases");a.href=v.url;studioNote.replaceChildren(document.createTextNode(v.installed+" → "+v.latest+" · "),a);}));
  const [dailyLabel,daily]=check(tr("Täglich nach Updates suchen"),s.daily);
  daily.onchange=()=>api("web/admin/updates","POST",{enabled:daily.checked}).catch(hint);box.append(dailyLabel);
  if(s.checked?.latest)box.append(el("p",s.version+" → "+s.checked.latest));
  const smtp=el("details");smtp.append(el("summary",tr("Passwortwiederherstellung per E-Mail")));box.append(smtp);
  const cfg=s.smtp,[l,en]=check(tr("E-Mail-Wiederherstellung aktivieren"),cfg.enabled);smtp.append(l);const fields={};
  for(const [k,label] of [["url",tr("Erreichbare HTTPS-Adresse")],["host","SMTP-Server"],["port","STARTTLS-Port"],["user",tr("SMTP-Benutzer")],["sender",tr("Absenderadresse")]]){
    fields[k]=input(k==="port"?"number":"text",cfg[k]||(k==="port"?587:""));smtp.append(labelControl(label,fields[k]));
  }
  smtp.append(el("p",tr("Das SMTP-Passwort wird auf dem Server als AUDILEGE_SMTP_PASSWORD hinterlegt.")));
  const recipient=input("email");smtp.append(tool(tr("Speichern"),async()=>{await api("web/admin/smtp","POST",Object.assign({enabled:en.checked},Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.value]))));studioNote.textContent=tr("Gespeichert.");}),labelControl(tr("Testempfänger"),recipient),tool(tr("Testmail senden"),async()=>{await api("web/admin/smtp","POST",{test:recipient.value});studioNote.textContent=tr("Testmail gesendet.");}));
}
const info=el("details",null,"panel");info.id="infoPanel";info.append(el("summary",tr("Info & Updates")));
const github=el("a","Audilege Server · GitHub");github.href="https://github.com/yourneeds-app/audilege-server";
info.append(github,el("p",tr("Python · SQLite · PyInstaller (Windows). Der optionale Abgleich verwendet STAlign, Ghost Story, FFmpeg und ein separat geladenes Sprachmodell.")));
$("settingsView").append(info);
async function recoveryScreen(){
  const cfg=await api("web/recovery/available","POST",{});
  if(!cfg.enabled)return;
  const request=action(tr("Passwort vergessen?"),()=>{const box=sheet(tr("Passwort zurücksetzen")),name=input();box.append(labelControl(tr("Benutzername oder bestätigte E-Mail-Adresse"),name),tool(tr("Link anfordern"),async()=>{await api("web/recovery/forgot","POST",{name:name.value});studioNote.textContent=tr("Wenn ein bestätigtes Konto existiert, erhältst du eine E-Mail.");}));});
  $("loginForm").after(request);
  $("profileView").append(action(tr("E-Mail-Adresse bestätigen"),()=>{const box=sheet(tr("E-Mail-Adresse bestätigen")),email=input("email");box.append(labelControl(tr("E-Mail-Adresse"),email),tool(tr("Bestätigungslink senden"),async()=>{await api("web/profile/email","POST",{email:email.value});studioNote.textContent=tr("Bestätigungslink versandt.");}));}));
  const m=/^#(reset|verify)=([A-Za-z0-9_-]+)$/.exec(location.hash);if(!m)return;
  history.replaceState(null,"",location.pathname+location.search);
  const box=sheet(m[1]==="reset"?tr("Neues Passwort"):tr("E-Mail-Adresse bestätigen")),pw=input("password");
  if(m[1]==="reset"){pw.autocomplete="new-password";box.append(labelControl(tr("Neues Passwort"),pw));}
  box.append(tool(tr("Bestätigen"),async()=>{await api("web/recovery/"+m[1],"POST",{code:m[2],password:pw.value});studio.close();$("loginError").textContent=tr("Gespeichert.");}));
}
recoveryScreen().catch(()=>{});
async function deviceSheet(uid=null){
  const path=uid?"web/admin/users/"+uid+"/devices":"web/profile/devices";
  const state=await api(path),box=sheet(tr("Gerätesitzungen"));
  for(const d of state.items)box.append(line(el("span",d.agent),tool(tr("Sitzung beenden"),async()=>{
    await api(path,"POST",{device:d.device});try{await deviceSheet(uid);}catch{location.reload();}
  })));
}
$("profileView").append(action(tr("Gerätesitzungen"),deviceSheet));
