const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const manifest=JSON.parse(fs.readFileSync(__dirname+'/site/snapshot/manifest.json','utf8'));
function setup(snapshot=manifest.snapshot_id,version=5,measurementSnapshot=snapshot){
 const requests=[],events=[],home='https://viewer.test/papermeta-analysis/';
 const network=async(input,options={})=>{const url=String(input);requests.push({url,...options});
  if(url===home+'task-backend.json')return Response.json({enabled:true,base_url:'https://tasks.test/'});
  if(url==='https://tasks.test/api/task-service')return Response.json({status:'READY',snapshot_id:snapshot,task_score_method_version:version,task_score_available:true,task_profile_available:true});
  if(url==='https://tasks.test/api/task-measurements')return Response.json({schema_version:'source-scoped-task-measurements-v2',snapshot_id:measurementSnapshot,groups:{}});
  return Response.json({state:'COMPLETE'});
 };
 const context={URL,Response,AbortController,setTimeout,clearTimeout,location:{hostname:'viewer.test'},CustomEvent:class{constructor(type){this.type=type;}},
  document:{currentScript:{src:home+'task-connection.js'},readyState:'loading',addEventListener(){},querySelector(){return null;},getElementById(id){return id==='snapshot-bootstrap'?{textContent:JSON.stringify({snapshot:{snapshot_id:manifest.snapshot_id}})}:null;}},
  window:{fetch:network,dispatchEvent:event=>events.push(event.type)}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/site/task-connection.js','utf8'),context);
 return{connection:context.window.RadarTaskConnection,window:context.window,requests,events};
}
test('interactive routes forward only to the configured task service after snapshot agreement',async()=>{
 const s=setup(),job='/api/interactive-jobs/'+'a'.repeat(43);
 assert(s.connection.supports('/api/interactive-jobs','POST'));assert(s.connection.supports(job,'GET'));assert(s.connection.supports(job,'DELETE'));
 assert(!s.connection.supports('/api/workspace','POST'));assert(!s.connection.supports('/api/status','GET'));assert(!s.connection.supports('/api/interactive-jobs/../admin','GET'));
 const r=await s.connection.request('/api/interactive-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});assert.equal(r.status,200);
 assert.equal(s.window.RadarTaskConnected,true);assert.equal(s.events[0],'radar:task-connected');assert.equal(s.requests.at(-1).url,'https://tasks.test/api/interactive-jobs');
 assert.equal(s.requests.at(-1).credentials,'omit');assert.equal(s.requests.at(-1).redirect,'error');
 assert.equal((await s.connection.request('/api/config',{method:'POST'})).status,404);assert(!s.requests.some(r=>r.url.includes('api/config')));
});
test('mismatched snapshot blocks submission and does not enable the task form',async()=>{
 const s=setup('old-snapshot'),r=await s.connection.request('/api/task-profile',{method:'POST',body:'{"description":"private task"}'});
 assert.equal(r.status,503);assert.equal((await r.json()).error,'task_snapshot_mismatch');assert(!s.window.RadarTaskConnected);assert(!s.requests.some(r=>r.method==='POST'));
});

test('v6 connects authoritative source rules before enabling task selection',async()=>{
 const s=setup(manifest.snapshot_id,6);await s.connection.connect();
 assert.equal(s.window.RadarTaskMeasurements.snapshot_id,manifest.snapshot_id);
 assert(s.requests.some(r=>r.url==='https://tasks.test/api/task-measurements'));
 assert(s.connection.supports('/api/task-measurements','GET'));assert(!s.connection.supports('/api/task-measurements','POST'));
});

test('v6 mismatched source rules block task transmission',async()=>{
 const s=setup(manifest.snapshot_id,6,'wrong-rules');
 const r=await s.connection.request('/api/task-score',{method:'POST',body:'{}'});
 assert.equal(r.status,503);assert.equal((await r.json()).error,'task_snapshot_mismatch');
 assert(!s.requests.some(r=>r.method==='POST'));assert(!s.window.RadarTaskConnected);
});
