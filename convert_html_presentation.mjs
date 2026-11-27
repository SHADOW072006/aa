import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "file:///C:/Program%20Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright/index.mjs";
import { Presentation, PresentationFile } from "file:///C:/Program%20Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const root=process.cwd();
const html=path.join(root,"deliverables","presentation.html");
const renderDir=path.join(root,"deliverables","presentation_html_render");
const output=path.join(root,"deliverables","TeleMonitor_HTML_Presentation.pptx");
await fs.mkdir(renderDir,{recursive:true});

const browser=await chromium.launch({headless:true,executablePath:"C:/Program Files/Google/Chrome/Application/chrome.exe"});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto(`file:///${html.replaceAll("\\","/")}`);
await page.waitForTimeout(300);
const total=await page.locator(".slide").count();
const pngs=[];
for(let i=1;i<=total;i++){
  await page.evaluate((n)=>{document.querySelectorAll(".slide").forEach(x=>x.classList.remove("active"));document.getElementById(`s${n}`).classList.add("active");document.getElementById("snum").textContent=`${n} / ${document.querySelectorAll(".slide").length}`;document.getElementById("pbar").style.width=`${n/document.querySelectorAll(".slide").length*100}%`;},i);
  await page.waitForTimeout(80);
  const out=path.join(renderDir,`slide-${String(i).padStart(2,"0")}.png`);
  await page.screenshot({path:out}); pngs.push(out);
}
await browser.close();

const deck=Presentation.create({slideSize:{width:1280,height:720}});
for(const img of pngs){
  const slide=deck.slides.add(); slide.background.fill="#06060a";
  const imageBytes=await fs.readFile(img);
  slide.images.add({blob:imageBytes,contentType:"image/png",alt:"Rendered HTML presentation slide",position:{left:0,top:0,width:1280,height:720}});
}
const file=await PresentationFile.exportPptx(deck); await file.save(output);
console.log(JSON.stringify({output,total,renderDir}));
