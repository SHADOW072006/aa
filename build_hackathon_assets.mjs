import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "file:///C:/Program%20Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const workspaceDir = process.cwd();
const outputDir = path.join(workspaceDir, "deliverables");
await fs.mkdir(outputDir, { recursive: true });

const W = 1280, H = 720;
const C = { bg: "#07111F", panel: "#101C2D", panel2: "#16243A", ink: "#F4F8FF", muted: "#9FB0C8", blue: "#3B82F6", cyan: "#22D3EE", green: "#34D399", amber: "#FBBF24", red: "#FB7185", line: "#263A56" };

function box(slide, x, y, w, h, fill=C.panel, radius="rounded-xl", line=C.line) {
  return slide.shapes.add({ geometry: "roundRect", position:{left:x,top:y,width:w,height:h}, fill, line:{style:"solid",fill:line,width:1}, borderRadius:radius });
}
function text(slide, value, x, y, w, h, size=18, color=C.ink, bold=false, align="left") {
  const shape = slide.shapes.add({ geometry:"textbox", position:{left:x,top:y,width:w,height:h}, fill:"none", line:{style:"solid",fill:"none",width:0} });
  shape.text = value;
  shape.text.style = { fontFamily:"Aptos", fontSize:`${size}pt`, color, bold, align, verticalAlignment:"middle", marginLeft:0, marginRight:0, marginTop:0, marginBottom:0 };
  return shape;
}
function pill(slide, label, x, y, w, color=C.blue) {
  box(slide,x,y,w,28,color,"rounded-full",color);
  text(slide,label,x,y+2,w,22,10,"#FFFFFF",true,"center");
}
function footer(slide, page, label="TeleMonitor · Public-source OSINT") {
  text(slide,label,56,682,440,18,9,C.muted);
  text(slide,String(page).padStart(2,"0"),1175,682,48,18,9,C.muted,false,"right");
}
function title(slide, kicker, heading, sub) {
  text(slide,kicker.toUpperCase(),58,48,300,20,10,C.cyan,true);
  text(slide,heading,58,78,1120,74,31,C.ink,true);
  if (sub) text(slide,sub,58,154,1060,42,15,C.muted);
}
function addSlide(deck) { const s=deck.slides.add(); s.background.fill=C.bg; return s; }
function dot(slide,x,y,color=C.cyan){ box(slide,x,y,10,10,color,"rounded-full",color); }

async function save(deck, name) {
  const pptx=await PresentationFile.exportPptx(deck);
  await pptx.save(path.join(outputDir,name));
}

// ===== Pitch deck =====
const pitch=Presentation.create({slideSize:{width:W,height:H}});
{
 const s=addSlide(pitch);
 text(s,"TELEMONITOR",60,58,320,28,15,C.cyan,true);
 text(s,"Public-source OSINT for\nsuspected illegal-trade posts",60,132,670,140,40,C.ink,true);
 text(s,"A review-first dashboard that turns public Telegram posts and imported datasets into traceable evidence, identifier links, and analyst-ready alerts.",60,300,600,74,18,C.muted);
 pill(s,"HACKATHON PROTOTYPE",60,402,182,C.blue);
 // visual anchor
 box(s,760,86,420,500,C.panel,"rounded-2xl");
 text(s,"Evidence-led triage",798,124,300,32,20,C.ink,true);
 const steps=[ ["01","Import / public feed","CSV, JSON, public channels"], ["02","Detect","Lexicon + ML + OCR"], ["03","Link","Phone, UPI, handles, wallets"], ["04","Review","Alerts, graph, PDF report"] ];
 steps.forEach((v,i)=>{const y=182+i*83; box(s,792,y,350,61,C.panel2); pill(s,v[0],806,y+16,46,i===3?C.green:C.blue); text(s,v[1],865,y+10,200,18,14,C.ink,true); text(s,v[2],865,y+31,240,16,10,C.muted); if(i<3){text(s,"↓",956,y+63,24,18,16,C.cyan,true,"center");}});
 text(s,"Public sources only · Analyst review required",60,637,600,24,12,C.muted);
 footer(s,1,"TeleMonitor · First-round submission");
}
{
 const s=addSlide(pitch); title(s,"The problem","Manual monitoring misses the link between posts","Public ads are fragmented across channels, use slang and images, and repeat the same contact details.");
 const cards=[ ["Scattered evidence","Posts, posters, captions and public links live across multiple sources."], ["Coded language","Slang, emojis and Hinglish reduce the value of simple keyword search."], ["Lost connections","Phones, UPI IDs and handles are rarely collated across channels." ] ];
 cards.forEach((c,i)=>{let x=58+i*382; box(s,x,260,350,220); pill(s,`0${i+1}`,x+26,288,38,[C.red,C.amber,C.cyan][i]); text(s,c[0],x+26,348,285,32,19,C.ink,true); text(s,c[1],x+26,392,285,64,14,C.muted);});
 text(s,"Need: a safe public-source workflow that makes each alert explainable and reviewable.",58,550,1050,38,20,C.green,true); footer(s,2);
}
{
 const s=addSlide(pitch); title(s,"What we built","A working OSINT dashboard across the core journey","The repository already provides usable ingestion, classification, entity extraction, graphing and reporting capabilities.");
 const items=[ ["Public collection + import","Telethon collector for public channels plus CSV/JSON import."], ["Slang-aware detection","Weighted crime lexicons with an optional TF-IDF classifier."], ["Image OCR","EasyOCR scans image posters in English and Hindi."], ["Identifier correlation","Phone, UPI, wallets, handles, emails and links become graph nodes."], ["Analyst workflow","Alerts, evidence views, dispositions, PDF dossiers and search."], ["Seed and pivot tools","Seed profiles and public-pivot review improve discovery control."] ];
 items.forEach((v,i)=>{const col=i%3,row=Math.floor(i/3),x=58+col*385,y=245+row*175; box(s,x,y,350,138); dot(s,x+24,y+26,[C.cyan,C.blue,C.green,C.amber,C.red,C.cyan][i]); text(s,v[0],x+46,y+17,270,30,16,C.ink,true); text(s,v[1],x+24,y+59,292,58,12,C.muted);}); footer(s,3);
}
{
 const s=addSlide(pitch); title(s,"How it works","From public post to analyst decision","The system preserves supporting evidence instead of surfacing a label alone.");
 const nodes=[["Public channel / dataset",65,C.blue],["Normalize + OCR",300,C.cyan],["Classify",535,C.amber],["Extract identifiers",770,C.green],["Alert + graph",1005,C.red]];
 nodes.forEach((n,i)=>{box(s,n[1],305,190,112,C.panel2); pill(s,String(i+1).padStart(2,"0"),n[1]+16,321,36,n[2]); text(s,n[0],n[1]+16,365,158,34,14,C.ink,true,"center"); if(i<nodes.length-1) text(s,"→",n[1]+195,344,35,30,20,C.cyan,true,"center");});
 box(s,168,505,945,76,C.panel); text(s,"Evidence snapshot: source · timestamp · original/OCR text · matched signals · identifiers · record hash · analyst disposition",198,526,885,30,15,C.muted,false,"center"); footer(s,4);
}
{
 const s=addSlide(pitch); title(s,"The product surface","One workspace for triage and linkage","The prototype already has operational routes for scanning, alerts, graphs, search, imports, seeds and pivot review.");
 // dashboard mock
 box(s,58,228,1162,368,"#0B1627","rounded-2xl");
 box(s,58,228,164,368,"#101C2D","rounded-2xl");
 text(s,"TM",81,252,118,26,15,C.ink,true); ["Dashboard","Alerts","Scanner","Entity Graph","Import Data"].forEach((v,i)=>text(s,v,82,305+i*42,115,20,11,i===1?C.cyan:C.muted,i===1));
 text(s,"Priority alerts",250,255,210,30,18,C.ink,true);
 [["Imported posts","1,358",C.cyan],["Flagged leads","583",C.amber],["Shared identifiers","70",C.green]].forEach((v,i)=>{box(s,250+i*220,300,195,86,C.panel);text(s,v[0],266+i*220,317,160,17,10,C.muted);text(s,v[1],266+i*220,344,160,27,22,v[2],true);});
 box(s,250,414,714,145,C.panel); text(s,"Evidence queue",270,432,160,22,14,C.ink,true); ["Suspected mule-account recruitment","Poster OCR matched · 2 identifiers","Pending review"].forEach((v,i)=>text(s,v,270,470+i*25,340,18,i===0?13:11,i===2?C.amber:C.muted,i===0));
 box(s,987,300,204,259,C.panel); text(s,"Entity graph",1006,320,150,22,14,C.ink,true); [[1040,404,C.cyan],[1106,448,C.green],[1067,497,C.amber]].forEach(p=>{dot(s,p[0],p[1],p[2]);}); text(s,"Phone ↔ UPI ↔ channels",1003,526,166,20,10,C.muted,"false","center"); footer(s,5);
}
{
 const s=addSlide(pitch); title(s,"What makes an alert useful","Evidence, not a label","Every finding should give an analyst enough context to verify, dismiss or escalate the lead.");
 box(s,58,232,720,342,C.panel,"rounded-2xl"); text(s,"Evidence snapshot",86,260,250,28,19,C.ink,true); const rows=[["Source","Public Telegram channel / imported public dataset"],["Observed","Timestamped text and optional OCR output"],["Detection","Category, confidence, matched terms and model version"],["Identifiers","Phone, UPI, public handle, wallet, domain"],["Relationship","Repeated identifier or public-source co-occurrence"],["Decision","Pending review, confirmed suspicious, benign or escalated"]]; rows.forEach((r,i)=>{text(s,r[0],86,310+i*37,118,20,11,C.cyan,true); text(s,r[1],218,310+i*37,510,20,11,C.muted);});
 box(s,817,232,403,342,C.panel2,"rounded-2xl"); text(s,"Safeguards",847,264,190,27,19,C.ink,true); ["Public sources only","No contact with sellers","Analyst review required","Synthetic/sample demo data","Audit trail and report export"].forEach((v,i)=>{dot(s,848,316+i*42,C.green);text(s,v,870,309+i*42,260,24,13,C.ink,i===0);}); footer(s,6);
}
{
 const s=addSlide(pitch); title(s,"First-round plan","Demo the dependable core, then extend safely","The submission is credible because it separates delivered features from planned improvements.");
 const cols=[ ["Built now",C.green,["CSV/JSON import","Public Telegram collector","Lexicon + ML classification","OCR for image posters","Identifier extraction","Entity graph","Alerts + PDF export"]], ["Next build",C.amber,["Evidence-led candidate queue","Better confidence vs priority scoring","Campaign deduplication","Seed test metrics","Scheduled polling repair","Cross-platform adapters"]] ];
 cols.forEach((c,i)=>{const x=58+i*571;box(s,x,245,535,310,C.panel);pill(s,c[0],x+28,270,105,c[1]);c[2].forEach((v,j)=>{dot(s,x+32,326+j*31,c[1]);text(s,v,x+53,317+j*31,410,22,13,C.ink);});});
 text(s,"Demo sequence: import sample data → inspect evidence alert → pivot on repeated identifier → view graph → export dossier.",58,603,1120,30,16,C.cyan,true); footer(s,7);
}
{
 const s=addSlide(pitch); title(s,"Why this should advance","A practical, safe prototype with a clear path to impact","TeleMonitor turns scattered public posts into a reviewable investigation workspace.");
 const facts=[["Aligned to the brief","Import, detect, extract, link, alert and report."],["Demonstrable now","Works with safe sample data without depending on unstable live search."],["Responsible by design","Public sources only. Findings remain analyst-reviewed leads." ]];
 facts.forEach((f,i)=>{const y=245+i*96;box(s,58,y,1140,72,C.panel);pill(s,`0${i+1}`,84,y+21,38,[C.cyan,C.green,C.amber][i]);text(s,f[0],145,y+14,285,23,16,C.ink,true);text(s,f[1],447,y+15,690,35,14,C.muted);});
 text(s,"TeleMonitor",58,580,520,56,34,C.ink,true); text(s,"Public-source monitoring. Evidence-led review. Better investigator context.",58,633,780,24,15,C.cyan); footer(s,8,"TeleMonitor · Thank you");
}
await save(pitch,"TeleMonitor_First_Round_Pitch.pptx");

// ===== Wireframe deck =====
const wire=Presentation.create({slideSize:{width:W,height:H}});
function wfHeader(s,num,name,desc){ text(s,"TELEMONITOR · WIREFRAME",48,34,340,20,10,C.cyan,true); text(s,`${num}. ${name}`,48,62,800,38,24,C.ink,true); text(s,desc,48,106,930,30,13,C.muted); }
function shell(s){ box(s,42,160,1196,490,"#FFFFFF","rounded-xl","#D8E2EF"); box(s,42,160,176,490,"#EAF0F7","rounded-xl","#D8E2EF"); text(s,"TM",68,186,72,25,16,"#17233A",true); ["Overview","Import","Alerts","Candidates","Graph","Reports"].forEach((v,i)=>text(s,v,70,241+i*45,110,20,12,i===2?"#2563EB":"#52627A",i===2)); }
{
 const s=addSlide(wire);wfHeader(s,"01","Dashboard","The operator sees workload, category coverage and the most actionable pending alerts.");shell(s);
 text(s,"Overview",246,188,200,25,17,"#17233A",true);[["Imported","1,358"],["Flagged","583"],["Pending","46"],["Shared IDs","70"]].forEach((v,i)=>{box(s,246+i*220,230,190,74,"#F4F7FB","rounded-lg","#D8E2EF");text(s,v[0],260+i*220,244,130,17,10,"#63748C");text(s,v[1],260+i*220,268,130,27,21,"#17233A",true);});
 box(s,246,330,570,260,"#F4F7FB","rounded-lg","#D8E2EF");text(s,"Priority evidence queue",268,350,260,24,14,"#17233A",true);["Suspected account-rental post","Image poster with phone and UPI","Shared handle across 3 channels"].forEach((v,i)=>{box(s,268,390+i*54,515,39,"#FFFFFF","rounded-md","#E3EAF2");text(s,v,282,400+i*54,410,18,11,"#334155",i===0);});
 box(s,845,330,345,260,"#F4F7FB","rounded-lg","#D8E2EF");text(s,"Category mix",867,350,160,24,14,"#17233A",true);["Financial","Drugs","Arms","Documents"].forEach((v,i)=>{text(s,v,868,397+i*40,90,17,11,"#52627A");box(s,965,400+i*40,[170,112,74,48][i],10,["#2563EB","#14B8A6","#F59E0B","#8B5CF6"][i],"rounded-full",["#2563EB","#14B8A6","#F59E0B","#8B5CF6"][i]);});
}
{
 const s=addSlide(wire);wfHeader(s,"02","Import and classify","A dependable demo entry point for CSV/JSON sample data and public-source records.");shell(s);
 text(s,"Import data",246,188,200,25,17,"#17233A",true);box(s,246,231,944,105,"#F4F7FB","rounded-lg","#D8E2EF");text(s,"Drop CSV or JSON sample file",276,252,330,24,15,"#17233A",true);text(s,"Required: source, channel, post text, timestamp. Optional: image path.",276,282,490,20,11,"#63748C");box(s,1021,258,135,38,"#2563EB","rounded-md","#2563EB");text(s,"Choose file",1021,267,135,18,11,"#FFFFFF",true,"center");
 text(s,"Preview and validation",246,365,260,24,14,"#17233A",true);box(s,246,400,944,182,"#FFFFFF","rounded-lg","#D8E2EF");["Source","Channel","Post preview","Status"].forEach((v,i)=>text(s,v,[270,390,560,1055][i],420,[80,120,410,90][i],18,10,"#63748C",true));["Telegram","Imported sample","Suspected sale message…","Ready"].forEach((v,i)=>text(s,v,[270,390,560,1055][i],455,[80,120,410,90][i],18,11,"#334155"));box(s,1008,525,148,34,"#2563EB","rounded-md","#2563EB");text(s,"Run classification",1008,534,148,16,10,"#FFFFFF",true,"center");
}
{
 const s=addSlide(wire);wfHeader(s,"03","Evidence alert detail","A reviewer gets the supporting post, extracted identifiers and a safe disposition action.");shell(s);
 text(s,"Alert #0241",246,188,180,25,17,"#17233A",true);pill(s,"PENDING REVIEW",445,187,124,"#F59E0B");box(s,246,230,555,333,"#F4F7FB","rounded-lg","#D8E2EF");text(s,"Observed post",270,252,180,22,14,"#17233A",true);text(s,"Public source · 24 Nov 2026 · 10:42",270,282,330,18,10,"#63748C");text(s,"Original text",270,323,130,20,11,"#52627A",true);box(s,270,352,506,70,"#FFFFFF","rounded-md","#E3EAF2");text(s,"Post body preserved exactly as collected…",286,371,470,28,11,"#334155");text(s,"Matched signals",270,447,130,20,11,"#52627A",true);pill(s,"account rental",270,476,104,"#2563EB");pill(s,"UPI",383,476,52,"#14B8A6");
 box(s,829,230,361,333,"#F4F7FB","rounded-lg","#D8E2EF");text(s,"Evidence summary",853,252,220,22,14,"#17233A",true);["Confidence 86%","Priority High","1 phone number","1 UPI ID","2 linked sources"].forEach((v,i)=>text(s,v,853,302+i*38,220,20,12,i<2?"#17233A":"#52627A",i===0));box(s,853,500,140,32,"#2563EB","rounded-md","#2563EB");text(s,"Open graph",853,508,140,16,10,"#FFFFFF",true,"center");box(s,1008,500,148,32,"#FFFFFF","rounded-md","#D8E2EF");text(s,"Mark benign",1008,508,148,16,10,"#334155",true,"center");
}
{
 const s=addSlide(wire);wfHeader(s,"04","Candidate queue","Weak or newly discovered channels wait for review instead of entering active monitoring automatically.");shell(s);
 text(s,"Candidates",246,188,180,25,17,"#17233A",true);box(s,246,228,944,38,"#F4F7FB","rounded-md","#D8E2EF");text(s,"All categories     Pending review     Public sources only",266,239,470,16,11,"#52627A");box(s,246,286,944,285,"#FFFFFF","rounded-lg","#D8E2EF");["Candidate","Discovery source","Evidence","Status","Action"].forEach((v,i)=>text(s,v,[266,485,690,914,1060][i],307,[180,170,180,115,90][i],17,10,"#63748C",true));[["@sample_channel","Seed variant","2 relevant posts","Pending","Review"],["@public_handle","Shared UPI","1 strong post","Pending","Review"],["@similar_channel","Text similarity","Possible duplicate","Duplicate","Inspect"]].forEach((r,j)=>r.forEach((v,i)=>text(s,v,[266,485,690,914,1060][i],347+j*58,[180,170,180,115,90][i],18,11,"#334155",i===4))); 
}
{
 const s=addSlide(wire);wfHeader(s,"05","Entity graph and report","The graph shows public co-occurrence while the report packages evidence for handoff.");shell(s);
 text(s,"Entity graph",246,188,180,25,17,"#17233A",true);box(s,246,228,640,335,"#F4F7FB","rounded-lg","#D8E2EF");[[420,360,"#2563EB","Channel A"],[550,322,"#14B8A6","UPI"],[690,390,"#F59E0B","Channel B"],[530,475,"#8B5CF6","Phone"]].forEach(n=>{box(s,n[0],n[1],90,42,n[2],"rounded-full",n[2]);text(s,n[3],n[0],n[1]+12,90,16,9,"#FFFFFF",true,"center");});text(s,"Shared identifier co-occurrence · requires analyst validation",272,530,540,18,10,"#63748C");box(s,914,228,276,335,"#F4F7FB","rounded-lg","#D8E2EF");text(s,"Evidence report",938,252,175,22,14,"#17233A",true);["Case summary","Evidence table","Identifiers","Review status","Record hashes"].forEach((v,i)=>text(s,v,940,300+i*36,175,18,11,"#52627A"));box(s,938,487,190,34,"#2563EB","rounded-md","#2563EB");text(s,"Export PDF",938,496,190,16,10,"#FFFFFF",true,"center");
}
await save(wire,"TeleMonitor_Wireframes.pptx");

console.log(JSON.stringify({outputDir},null,2));
