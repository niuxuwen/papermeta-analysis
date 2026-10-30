const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),zlib=require('node:zlib');
const V=require('./site/radar-viz.js');
for(const name of ['coding','medical','math','data','extraction','visual','law','science'])test('v9 real '+name+' keeps direct/related scopes separate without changing scores',()=>{
 const path=__dirname+'/validation/task-v9-'+name+'-20261031.json.gz';
 const report=JSON.parse(zlib.gunzipSync(fs.readFileSync(path))).task_index;
 const before=JSON.stringify(report),view=V.taskOverview(report);
 assert.equal(view.models,new Set(report.models.map(m=>m.model_canonical)).size);
 assert.equal(view.panels.flatMap(p=>p.models).length,report.models.length);
 for(const scenario of view.scenarios)for(const panel of scenario.panels){
  assert.equal(scenario.evidenceKind,panel.evidenceKind);
  assert(panel.models.every(m=>m.evidence_kind===scenario.evidenceKind));
  assert(panel.entries.every(e=>e.evidence_kind===scenario.evidenceKind));
 }
 assert.equal(JSON.stringify(report),before);
 if(['medical','law','extraction','visual'].includes(name))assert(view.scenarios.every(s=>s.evidenceKind==='RELATED_REFERENCE'));
 if(name==='visual')assert(view.benchmarks>0);
});
test('v9 frontend contains two evidence sections and audited umbrella matching',()=>{
 const code=fs.readFileSync(__dirname+'/site/radar.js','utf8');
 assert(code.includes("['DIRECT_TASK','直接任务成绩'"));assert(code.includes("['RELATED_REFERENCE','相关能力参考'"));
 const viz=fs.readFileSync(__dirname+'/site/radar-viz.js','utf8');assert(viz.includes("['image','audio','video'].includes(m)"));
});
