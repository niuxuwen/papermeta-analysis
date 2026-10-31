const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const manifest=JSON.parse(fs.readFileSync(__dirname+'/site/snapshot/manifest.json','utf8'));
function setup(snapshot=manifest.snapshot_id,version=5,measurementSnapshot=snapshot,schema=version>=7?'source-scoped-task-measurements-v3':'source-scoped-task-measurements-v2',versioned=false){
 const requests=[],events=[],home='https://viewer.test/papermeta-analysis/';
 const network=async(input,options={})=>{const url=String(input);requests.push({url,...options});
  if(url===home+'task-backend.json')return Response.json({enabled:true,base_url:'https://tasks.test/'});
  if(url.startsWith('https://tasks.test/api/task-service?'))return Response.json({status:'READY',snapshot_id:versioned?new URL(url).searchParams.get('snapshot_id'):snapshot,task_score_method_version:version,task_score_available:true,task_profile_available:true,versioned_snapshots:versioned});
  if(new URL(url).pathname==='/api/task-measurements')return Response.json({schema_version:schema,snapshot_id:measurementSnapshot,groups:{}});
  if(new URL(url).pathname==='/api/interactive-jobs'&&options.method==='POST')return Response.json({id:'b'.repeat(43),state:'QUEUED'},{status:202});
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
 const r=await s.connection.request('/api/interactive-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});assert.equal(r.status,202);
 assert.equal(s.window.RadarTaskConnected,true);assert.equal(s.events[0],'radar:task-connected');assert.equal(s.requests.at(-1).url,'https://tasks.test/api/interactive-jobs');
 assert.equal(s.requests.at(-1).credentials,'omit');assert.equal(s.requests.at(-1).redirect,'error');
 assert.equal((await s.connection.request('/api/config',{method:'POST'})).status,404);assert(!s.requests.some(r=>r.url.includes('api/config')));
});

test('versioned gateway pins health, score and job polling to the page publication',async()=>{
 const s=setup(manifest.snapshot_id,8,manifest.snapshot_id,'source-scoped-task-measurements-v3',true);
 s.window.RadarLoadTaskEvidence=async()=>({task_method_version:8,measurements:{schema_version:'source-scoped-task-measurements-v3',snapshot_id:manifest.snapshot_id,groups:{}}});
 const body=JSON.stringify({kind:'profile',payload:{description:'整理医学文献'}});
 const created=await s.connection.request('/api/interactive-jobs',{method:'POST',body});
 assert.equal(created.status,202);assert.equal(s.requests.at(-1).body,body);
 assert.equal(new URL(s.requests.at(-1).url).searchParams.get('snapshot_id'),manifest.snapshot_id);
 s.window.RadarHomeSnapshot={snapshot_id:'f'.repeat(24)};
 await s.connection.request('/api/interactive-jobs/'+'b'.repeat(43));
 assert.equal(new URL(s.requests.at(-1).url).searchParams.get('snapshot_id'),manifest.snapshot_id);
 await s.connection.connect({measurements:false});
 assert.equal(new URL(s.requests.at(-1).url).searchParams.get('snapshot_id'),'f'.repeat(24));
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

test('v7 source schema enables the actual broad-reference service',async()=>{
 const s=setup(manifest.snapshot_id,7);await s.connection.connect();
 assert.equal(s.window.RadarTaskMeasurements.schema_version,'source-scoped-task-measurements-v3');
 assert(s.window.RadarTaskConnected);
});

test('v9 upgrades old prepared inputs only through same-snapshot authoritative rules',async()=>{
 const s=setup(manifest.snapshot_id,9,manifest.snapshot_id,'source-scoped-task-measurements-v4',true);
 s.window.RadarLoadTaskEvidence=async()=>({task_method_version:8,measurements:{schema_version:'source-scoped-task-measurements-v3',snapshot_id:manifest.snapshot_id,groups:{}}});
 await s.connection.connect();assert.equal(s.window.RadarTaskMeasurements.schema_version,'source-scoped-task-measurements-v4');
 assert(s.requests.some(r=>new URL(r.url).pathname==='/api/task-measurements'));
});
test('v9 rejects old role projection even when snapshot identity matches',async()=>{
 const s=setup(manifest.snapshot_id,9,manifest.snapshot_id,'source-scoped-task-measurements-v3');
 assert.equal((await s.connection.request('/api/task-score',{method:'POST',body:'{}'})).status,503);
 assert(!s.requests.some(r=>r.method==='POST'));
});

test('v10 replaces v9 preview rules with the same-snapshot v5 source projection',async()=>{
 const s=setup(manifest.snapshot_id,10,manifest.snapshot_id,'source-scoped-task-measurements-v5',true);
 s.window.RadarLoadTaskEvidence=async()=>({task_method_version:9,measurements:{schema_version:'source-scoped-task-measurements-v4',snapshot_id:manifest.snapshot_id,groups:{}}});
 await s.connection.connect();assert.equal(s.window.RadarTaskMeasurements.schema_version,'source-scoped-task-measurements-v5');
 assert(s.requests.some(r=>new URL(r.url).pathname==='/api/task-measurements'));
});

test('v10 refuses a v4 projection even when the snapshot matches',async()=>{
 const s=setup(manifest.snapshot_id,10,manifest.snapshot_id,'source-scoped-task-measurements-v4');
 assert.equal((await s.connection.request('/api/task-score',{method:'POST',body:'{}'})).status,503);
 assert(!s.requests.some(r=>r.method==='POST'));
});

test('v11 upgrades old preview from the same pinned snapshot and requires v6 roles',async()=>{
 const s=setup(manifest.snapshot_id,11,manifest.snapshot_id,'source-scoped-task-measurements-v6',true);
 s.window.RadarLoadTaskEvidence=async()=>({task_method_version:10,measurements:{schema_version:'source-scoped-task-measurements-v5',snapshot_id:manifest.snapshot_id,groups:{}}});
 await s.connection.connect();assert.equal(s.window.RadarTaskMeasurements.schema_version,'source-scoped-task-measurements-v6');
 assert(s.requests.some(r=>new URL(r.url).pathname==='/api/task-measurements'));
 const stale=setup(manifest.snapshot_id,11,manifest.snapshot_id,'source-scoped-task-measurements-v5');
 assert.equal((await stale.connection.request('/api/task-score',{method:'POST',body:'{}'})).status,503);
 assert(!stale.requests.some(r=>r.method==='POST'));
});

test('v7 does not silently accept obsolete task attribution rules',async()=>{
 const s=setup(manifest.snapshot_id,7,manifest.snapshot_id,'source-scoped-task-measurements-v2');
 const r=await s.connection.request('/api/task-score',{method:'POST',body:'{}'});
 assert.equal(r.status,503);assert(!s.requests.some(r=>r.method==='POST'));
});

test('static v8 task rules avoid downloading the same rules from the remote tunnel',async()=>{
 const s=setup(manifest.snapshot_id,8);
 s.window.RadarLoadTaskEvidence=async()=>({task_method_version:8,measurements:{schema_version:'source-scoped-task-measurements-v3',snapshot_id:manifest.snapshot_id,groups:{}}});
 await s.connection.connect();assert(s.window.RadarTaskConnected);
 assert(!s.requests.some(r=>r.url==='https://tasks.test/api/task-measurements'));
});

test('static rules from another scoring version block task submission',async()=>{
 const s=setup(manifest.snapshot_id,8);
 s.window.RadarLoadTaskEvidence=async()=>({task_method_version:7,measurements:{schema_version:'source-scoped-task-measurements-v3',snapshot_id:manifest.snapshot_id,groups:{}}});
 const r=await s.connection.request('/api/task-score',{method:'POST',body:'{}'});
 assert.equal(r.status,503);assert(!s.requests.some(r=>r.method==='POST'));
});

test('profile analysis reaches the backend without waiting for task-evidence download',async()=>{
 const s=setup(manifest.snapshot_id,8);let resolveRules;
 s.window.RadarLoadTaskEvidence=()=>new Promise(resolve=>{resolveRules=resolve;});
 const profile=await s.connection.request('/api/interactive-jobs',{method:'POST',body:JSON.stringify({kind:'profile',payload:{description:'整理医学文献'}})});
 assert.equal(profile.status,202);assert(s.requests.some(r=>r.method==='POST'));assert.equal(resolveRules,undefined);
 const before=s.requests.filter(r=>r.method==='POST').length;
 const score=s.connection.request('/api/task-score',{method:'POST',body:'{}'});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(s.requests.filter(r=>r.method==='POST').length,before);
 resolveRules({task_method_version:8,measurements:{schema_version:'source-scoped-task-measurements-v3',snapshot_id:manifest.snapshot_id,groups:{}}});
 assert.equal((await score).status,200);
});
