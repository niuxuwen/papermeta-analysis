const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib'),{webcrypto}=require('node:crypto');
const site=__dirname+'/site/',manifest=JSON.parse(fs.readFileSync(site+'snapshot/manifest.json'));
const lite=JSON.parse(zlib.gunzipSync(fs.readFileSync(site+manifest.task_evidence.path)));
const source=fs.readFileSync(site+'radar.js','utf8'),ctx={};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function decodeSnapshot('),source.indexOf('  async function fetchSnapshotJSON(')),ctx);
const full=ctx.decodeSnapshot(JSON.parse(zlib.gunzipSync(Buffer.concat(manifest.parts.map(p=>fs.readFileSync(site+p.path))))));
const V=require('./site/radar-viz.js'),snapshot=V.visitorSnapshot(full);
const rules=JSON.parse(fs.readFileSync(__dirname+'/validation/task-measurements-v8-real.json'));
const report=JSON.parse(fs.readFileSync(__dirname+'/validation/task-score-v8-multidomain.json'));
V.setModelRegistry(full.model_registry);
for(const [name,item]of Object.entries(report.profiles))test('compact task data preserves the complete real '+name+' preview',()=>{
 V.setTaskMeasurements(rules);const expected=V.taskMatchPreview(snapshot,item.profile);
 V.setTaskMeasurements(lite.measurements);const actual=V.taskMatchPreview(lite.snapshot,item.profile);
 assert.deepEqual(actual,expected);assert.equal(actual.benchmarks,item.matched_benchmarks);
});

function adapter(corrupt=false,failures=0){
 const requests=[],home='https://viewer.test/papermeta-analysis/';
 const original=async(input)=>{const url=new URL(input),path=url.pathname.slice('/papermeta-analysis/'.length);requests.push(path);
  if(failures-->0)throw new DOMException('signal is aborted without reason','AbortError');
  const bytes=fs.readFileSync(site+path);return new Response(corrupt&&path===manifest.task_evidence.path?Buffer.concat([bytes,Buffer.from('x')]):bytes);};
 const context={URL,Request,Response,Blob,DecompressionStream,TextDecoder,TextEncoder,Uint8Array,Array,DOMException,AbortController,setTimeout,clearTimeout,crypto:webcrypto,console,location:{href:home},
  document:{currentScript:{src:home+'snapshot-adapter.js'},readyState:'loading',addEventListener(){},getElementById(){return{textContent:JSON.stringify({manifest,snapshot:{snapshot_id:manifest.snapshot_id}})};}},window:{fetch:original}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(site+'snapshot-adapter.js','utf8'),context);
 return{context,requests};
}
test('task loader fetches one verified small asset and never the complete archive',async()=>{
 const s=adapter();const [a,b]=await Promise.all([s.context.window.RadarLoadTaskEvidence(),s.context.window.RadarLoadTaskEvidence()]);
 assert.strictEqual(a,b);assert.equal(a.snapshot_id,manifest.snapshot_id);
 assert.deepEqual(s.requests,[manifest.task_evidence.path]);assert(manifest.task_evidence.bytes<300000);
 assert(manifest.task_evidence.bytes<manifest.parts.reduce((n,p)=>n+p.bytes,0)*.03);
});
test('tampered task asset fails integrity verification',async()=>{
 await assert.rejects(adapter(true).context.window.RadarLoadTaskEvidence(),/TASK_EVIDENCE_INTEGRITY_FAILURE/);
});
test('interrupted real task asset retries once and retains integrity checks',async()=>{
 const s=adapter(false,1),data=await s.context.window.RadarLoadTaskEvidence();
 assert.equal(data.snapshot_id,manifest.snapshot_id);assert.deepEqual(s.requests,[manifest.task_evidence.path,manifest.task_evidence.path]);
});
test('exhausted task downloads show a readable error and allow a later retry',async()=>{
 const s=adapter(false,2);await assert.rejects(s.context.window.RadarLoadTaskEvidence(),/任务评测数据读取超时或连接中断/);
 assert.equal((await s.context.window.RadarLoadTaskEvidence()).snapshot_id,manifest.snapshot_id);
});
test('task analysis submits while candidate data is still downloading',async()=>{
 const nodes=new Map(),requests=[],state={revision:0};let applied=false;
 const c={taskState:state,AbortController,performance:{now:()=>0},setInterval:()=>1,clearInterval(){},backgroundStatus:{},
  $(id){if(!nodes.has(id))nodes.set(id,{value:id==='task-description'?'整理医学文献':'',disabled:false,hidden:true});return nodes.get(id);},
  loadTaskEvidenceForPreview:()=>new Promise(()=>{}),refresh(){throw Error('Full archive must not block profile submission');},
  dirtyTask(){state.revision++;},taskMessage(){},async taskPost(route,payload){requests.push([route,payload]);return{profile:{description:payload.description}};},applyProfile(){applied=true;}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('  async function analyseTask()'),source.indexOf('  function setCandidateSelection(')),c);
 await c.analyseTask();assert(applied);assert.equal(requests[0][0],'api/task-profile');assert.equal(requests[0][1].description,'整理医学文献');
});
