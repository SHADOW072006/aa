import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, PresentationFile } from "file:///C:/Program%20Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const root=path.join(process.cwd(),"deliverables");
for (const file of ["TeleMonitor_HTML_Presentation.pptx"]) {
  const deck=await PresentationFile.importPptx(await FileBlob.load(path.join(root,file)));
  const dir=path.join(root,path.basename(file,".pptx")+"_render");
  await fs.mkdir(dir,{recursive:true});
  for (const [i,slide] of deck.slides.items.entries()) {
    const blob=await deck.export({slide,format:"png",scale:1});
    await fs.writeFile(path.join(dir,`slide-${String(i+1).padStart(2,"0")}.png`),new Uint8Array(await blob.arrayBuffer()));
  }
  console.log(file, deck.slides.items.length, dir);
}
