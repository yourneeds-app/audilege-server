"use strict";
const numbers=new Intl.NumberFormat(uiLanguage);
const dayMs=86400000;
function dayKey(time){return new Date(time).toISOString().slice(0,10);}
const dateLabel=new Intl.DateTimeFormat(uiLanguage,{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"});
const monthLabel=new Intl.DateTimeFormat(uiLanguage,{month:"short",timeZone:"UTC"});

function statCard(label,value){
  const card=el("div",null,"statCard");
  card.append(el("strong",value),el("span",label));
  return card;
}
function activityRange(period,anchor){
  const date=new Date(anchor),year=date.getUTCFullYear(),month=date.getUTCMonth();
  if(period==="year")return [Date.UTC(year,0,1),Date.UTC(year+1,0,1)];
  if(period==="month")return [Date.UTC(year,month,1),Date.UTC(year,month+1,1)];
  const start=anchor-((date.getUTCDay()+6)%7)*dayMs;
  return [start,start+7*dayMs];
}

function dashboardCalendar(start,end,today,days){
  const panel=el("section",null,"panel yearPanel"),scroll=el("div",null,"calendarScroll");
  const months=el("div",null,"yearMonths"),grid=el("div",null,"yearGrid");
  const year=new Date(start).getUTCFullYear();
  const peak=Math.max(1,...Object.entries(days).filter(([day])=>day.startsWith(year+"-")).map(([,value])=>value));
  panel.append(el("h2",tr("Aktivitätskalender")),scroll);
  scroll.append(months,grid);
  for(let month=0;month<12;month++)months.append(el("span",monthLabel.format(new Date(Date.UTC(year,month,1)))));
  for(let i=0;i<(new Date(start).getUTCDay()+6)%7;i++)grid.append(el("i"));
  for(let at=start;at<Math.min(end,today+dayMs);at+=dayMs){
    const value=days[dayKey(at)]||0,cell=el("i",null,"heat");
    cell.dataset.level=value?String(Math.max(1,Math.ceil(4*Math.sqrt(value/peak)))):"0";
    cell.title=dateLabel.format(new Date(at))+" · "+duration(value/1000);grid.append(cell);
  }
  return panel;
}

function listeningDashboard(body,data){
  const today=Date.parse(dayKey(Date.now())+"T00:00:00Z");
  const modes={listen:tr("Hören"),read:tr("Lesen"),tts:tr("Vorlesen")};
  const filters=el("div",null,"statsFilters");
  const kind=choices([["",tr("Alle Aktivitäten")],...Object.entries(modes)],"");
  const range=choices([["week",tr("Woche")],["month",tr("Monat")],["year",tr("Jahr")],["all",tr("Gesamt")]],"week");
  kind.setAttribute("aria-label",tr("Aktivität"));
  range.setAttribute("aria-label",tr("Zeitraum"));
  const prev=el("button","←"),next=el("button","→");
  prev.setAttribute("aria-label",tr("Vorheriger Zeitraum"));
  next.setAttribute("aria-label",tr("Nächster Zeitraum"));
  const heading=el("strong"), output=el("div");
  heading.setAttribute("aria-live","polite");
  filters.append(kind,range,prev,heading,next);
  body.append(filters,output);
  let anchor=today, selection=null;
  function shift(direction){
    const [start,end]=activityRange(range.value,anchor);
    anchor=direction<0?start-dayMs:end;
    selection=null;render();
  }
  prev.onclick=()=>shift(-1);next.onclick=()=>shift(1);
  kind.onchange=()=>{selection=null;render();};
  range.onchange=()=>{anchor=today;selection=null;render();};

  function render(){
    const period=range.value,activeKind=kind.value;
    const activities=activeKind?[data.activities[activeKind]].filter(Boolean):Object.values(data.activities);
    const activitiesDays={},titles=new Map();
    for(const activity of activities){
      for(const [d,m] of Object.entries(activity.days))activitiesDays[d]=(activitiesDays[d]||0)+m;
      for(const [key,item] of Object.entries(activity.books)){
        if(!titles.has(key))titles.set(key,{title:item.title,author:item.author,days:{}});
        const timeline=titles.get(key).days;
        for(const [d,m] of Object.entries(item.days))timeline[d]=(timeline[d]||0)+m;
      }
    }
    const keys=Object.keys(activitiesDays).sort();
    const [start,end]=period==="all"?
      [Date.UTC(Number(keys[0]?.slice(0,4)||new Date(today).getUTCFullYear()),0,1),today+dayMs]:
      activityRange(period,anchor);
    const rangeStart=dayKey(start),rangeEnd=dayKey(end);
    const inRange=key=>key>=rangeStart&&key<rangeEnd;
    const visibleDays=keys.filter(inRange);
    const overall=visibleDays.reduce((sum,d)=>sum+activitiesDays[d],0);
    heading.textContent=period==="all"?tr("Gesamt"):
      dateLabel.format(new Date(start))+" – "+dateLabel.format(new Date(Math.min(end-dayMs,today)));
    prev.hidden=next.hidden=period==="all";
    next.disabled=end>today;
    const rank=window=>[...titles].map(([id,item])=>{
      const millis=Object.entries(item.days).reduce((sum,[d,m])=>sum+(window(d)?m:0),0);
      return {id,...item,millis};
    }).filter(item=>item.millis>0).sort((a,b)=>b.millis-a.millis);
    const cards=el("div",null,"statCards");
    cards.append(statCard(tr("Aktivität im Zeitraum"),duration(overall/1000)),
      statCard(tr("Aktive Tage"),numbers.format(visibleDays.length)),
      statCard(tr("Aktive Titel"),numbers.format(rank(inRange).length)),
      statCard(tr("Aktuelle Serie"),numbers.format(data.streak.current)+" "+tr(data.streak.current===1?"Tag":"Tage")),
      statCard(tr("Längste Serie"),numbers.format(data.streak.best)+" "+tr(data.streak.best===1?"Tag":"Tage")),
      statCard(tr("Täglicher Ø"),duration(overall/1000/Math.max(1,(Math.min(end,today+dayMs)-start)/dayMs))));
    const chart=el("section",null,"panel");
    chart.append(el("h2",tr("Aktivität nach Zeitraum")));
    const bars=el("div",null,"activityBars"),chartScroll=el("div",null,"activityChartScroll");
    const buckets=[];
    for(let at=start;at<Math.min(end,today+dayMs);){
      const d=new Date(at),year=d.getUTCFullYear(),month=d.getUTCMonth();
      const until=period==="all"?Date.UTC(year+1,0,1):period==="year"?Date.UTC(year,month+1,1):at+dayMs;
      const from=dayKey(at),to=dayKey(until);
      const millis=visibleDays.filter(key=>key>=from&&key<to).reduce((sum,key)=>sum+activitiesDays[key],0);
      const label=period==="all"?String(year):period==="year"?monthLabel.format(d):String(d.getUTCDate());
      buckets.push({at,from,to,label,millis});at=until;
    }
    const peak=Math.max(1,...buckets.map(b=>b.millis));
    const selectedLabel=el("p",null,"muted");
    selectedLabel.setAttribute("aria-live","polite");
    const details=el("div",null,"activitySplit");
    function showDetails(){
      const window=key=>inRange(key)&&(!selection||(key>=selection.from&&key<selection.to));
      selectedLabel.textContent=selection?
        dateLabel.format(new Date(selection.at))+" · "+duration(selection.millis/1000):tr("Wähle einen Balken, um den Zeitraum einzugrenzen.");
      const top=el("section",null,"panel"),recent=el("section",null,"panel recentList");
      top.append(el("h2",tr("Aktivität pro Titel")));
      const ranked=rank(window);
      function showTitles(expanded){
        while(top.childNodes.length>1)top.lastChild.remove();
        for(const item of ranked.slice(0,expanded?ranked.length:10)){
          const row=el("div",null,"row statsTitleRow"),book=books.find(b=>"orbit:"+b.id===item.id);
          if(book){
            const link=action("",()=>openReader(book),"textButton");
            link.append(cover(book),el("span",item.title));row.append(link);
          }else row.append(el("span",item.title));
          row.append(el("strong",duration(item.millis/1000)));top.append(row);
        }
        if(!ranked.length)top.append(el("p",tr("Noch keine Sitzungen erfasst.")));
        if(ranked.length>10)top.append(action(tr(expanded?"Weniger anzeigen":"Mehr anzeigen"),()=>showTitles(!expanded),"textButton"));
      }
      showTitles(false);
      recent.append(el("h2",tr("Letzte Aktivitäten")));
      const events=data.events.filter(event=>(!activeKind||event.kind===activeKind)&&window(event.day));
      for(const event of events.slice(0,10)){
        const row=el("div",null,"row"),label=el("div");
        const when=event.started?new Date(event.started).toLocaleString(uiLanguage,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}):dateLabel.format(new Date(event.day));
        label.append(el("strong",event.title),el("small",(modes[event.kind]||event.kind)+" · "+when));
        row.append(label,el("span",duration(event.seconds)));recent.append(row);
      }
      if(!events.length)recent.append(el("p",tr("Keine jüngeren Sitzungen in diesem Zeitraum.")));
      details.replaceChildren(top,recent);
    }
    for(const bucket of buckets){
      const button=el("button"),shaft=el("span",null,"activityBarTrack"),bar=el("i");
      bar.style.height=(100*bucket.millis/peak)+"%";
      shaft.append(bar);
      button.append(shaft,el("span",bucket.label));
      button.setAttribute("aria-label",dateLabel.format(new Date(bucket.at))+" · "+duration(bucket.millis/1000));
      button.setAttribute("aria-pressed",String(selection===bucket));
      button.onclick=()=>{
        selection=selection===bucket?null:bucket;
        [...bars.children].forEach(child=>child.setAttribute("aria-pressed",String(child===button&&Boolean(selection))));
        showDetails();
      };
      bars.append(button);
    }
    chartScroll.append(bars);chart.append(chartScroll,selectedLabel);
    output.replaceChildren(cards,chart,details);
    if(period==="year")output.append(dashboardCalendar(start,end,today,activitiesDays));
    showDetails();
  }
  render();
}
