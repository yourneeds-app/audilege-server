"use strict";
const numbers = new Intl.NumberFormat(uiLanguage);
const prettyDay = new Intl.DateTimeFormat(uiLanguage,{day:"numeric",month:"short",timeZone:"UTC"});
const dayMs=86400000;
function dayKey(time){return new Date(time).toISOString().slice(0,10);}
function statCard(label,value){
  const card=el("div",null,"statCard");card.append(el("strong",value),el("span",label));return card;
}
function listeningDashboard(body,s) {
  const days=s.listeningDays,keys=Object.keys(days).sort();
  const today=dayKey(Date.now()),midnight=Date.parse(today+"T00:00:00Z");
  const total=Object.values(days).reduce((a,b)=>a+b,0);
  const counts=el("div",null,"statCards");
  counts.append(statCard(tr("Gehörte Medien"),numbers.format(s.heardMedia)),statCard(tr("Hörtage"),numbers.format(keys.length)),
    statCard(tr("Hörminuten"),numbers.format(Math.round(total/60))));
  body.append(counts);
  const area=el("div",null,"activitySplit"),week=el("section",null,"panel"),recent=el("section",null,"panel");
  body.append(area);area.append(week,recent);
  week.append(el("h2",tr("Hörminuten der letzten sieben Tage")));
  const bars=el("div",null,"weekBars"),weekDays=Array.from({length:7},(_,i)=>dayKey(midnight+(i-6)*dayMs));
  const high=Math.max(60,...weekDays.map(d=>days[d]||0));week.append(bars);
  for(const day of weekDays){
    const col=el("div"),value=days[day]||0,bar=el("i");
    bar.style.height=(100*value/high)+"%";
    col.title=prettyDay.format(new Date(day))+" · "+duration(value);
    col.append(el("small",numbers.format(Math.round(value/60))),bar,el("span",new Date(day).toLocaleDateString(uiLanguage,{weekday:"short",timeZone:"UTC"})));
    bars.append(col);
  }
  const sum=weekDays.reduce((a,k)=>a+(days[k]||0),0);
  const weekly=el("div",null,"weeklySummary");
  weekly.append(statCard(tr("7 Tage gesamt"),duration(sum)),statCard(tr("Täglicher Ø"),duration(sum/7)),statCard(tr("Aktuelle Serie"),s.streak.current+" "+tr(s.streak.current===1?"Tag":"Tage")),statCard(tr("Längste Serie"),s.streak.best+" "+tr(s.streak.best===1?"Tag":"Tage")));
  week.append(weekly);
  recent.append(el("h2",tr("Letzte Aktivitäten")));
  const list=el("div",null,"recentList");
  function events(expanded){
    list.replaceChildren();
    if(!s.events.length)list.append(el("p",tr("Noch keine Sitzungen erfasst.")));
    for(const e of s.events.slice(0,expanded?100:5)){
      const row=el("div",null,"row"),description=el("div");
      const when=e.started?new Date(e.started).toLocaleString(uiLanguage,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}):prettyDay.format(new Date(e.day));
      description.append(el("strong",e.title||tr("Unbekannter Titel")),el("small",({read:tr("Lesen"),listen:tr("Hören"),tts:tr("Vorlesen")}[e.kind]||e.kind)+" · "+when));
      row.append(description,el("span",duration(e.seconds)));list.append(row);
    }
    if(s.events.length>5){const more=el("button",expanded?tr("Weniger anzeigen"):tr("Mehr anzeigen"),"textButton");more.onclick=()=>events(!expanded);list.append(more);}
  }
  events(false);recent.append(list);
  const calendar=el("section",null,"panel yearPanel"),heading=el("header"),select=el("select"),details=el("div");
  select.setAttribute("aria-label",tr("Jahr auswählen"));
  const years=[...new Set([today.slice(0,4),...keys.map(k=>k.slice(0,4))])].sort().reverse();
  select.replaceChildren(...years.map(y=>new Option(y,y)));
  heading.append(el("h2",tr("Dein Hörjahr")),select);calendar.append(heading,details);body.append(calendar);
  function renderYear(){
    const y=select.value,start=Date.UTC(+y,0,1),end=Math.min(Date.UTC(+y+1,0,1),midnight+dayMs);
    const values=keys.filter(k=>k.startsWith(y+"-")),peak=Math.max(1,...values.map(k=>days[k]));
    details.replaceChildren(el("p",values.length+tr(" Hörtage · ")+duration(values.reduce((a,k)=>a+days[k],0))));
    const scroll=el("div",null,"calendarScroll"),months=el("div",null,"yearMonths"),grid=el("div",null,"yearGrid");
    for(let month=0;month<12;month++)months.append(el("span",new Date(Date.UTC(+y,month,1)).toLocaleDateString(uiLanguage,{month:"short",timeZone:"UTC"})));
    for(let i=0;i<(new Date(start).getUTCDay()+6)%7;i++)grid.append(el("i"));
    for(let t=start;t<end;t+=dayMs){
      const day=dayKey(t),value=days[day]||0,cell=el("i");
      cell.className="heat";cell.dataset.level=value?String(Math.max(1,Math.ceil(4*Math.sqrt(value/peak)))):"0";
      cell.title=prettyDay.format(new Date(t))+" · "+duration(value);grid.append(cell);
    }
    scroll.append(months,grid);details.append(scroll);
  }
  select.onchange=renderYear;renderYear();
}
