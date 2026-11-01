const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),zlib=require('node:zlib'),V=require('./site/radar-viz.js');
const load=p=>JSON.parse(zlib.gunzipSync(fs.readFileSync(__dirname+'/validation/'+p)));
const inputs=load('task-readiness-followup-inputs.json.gz'),meta=load('task-v12-measurements-real.json.gz');
const snapshot={snapshot_id:inputs.snapshot_id,index:inputs.index,benchmarks:inputs.catalog};
V.setTaskMeasurements(meta);
for(const name of ['coding','medical','law','math','science','data','meeting_audio','web_factcheck'])test('v12 same-source preview and result agree: '+name,()=>{
 const r=load('task-v12-result-'+name+'.json.gz').task_index,before=JSON.stringify(r),p=V.taskMatchPreview(snapshot,r.profile),view=V.taskOverview(r);
 assert.equal(meta.snapshot_id,inputs.snapshot_id);assert.equal(meta.schema_version,'source-scoped-task-measurements-v7');
 assert.deepEqual(p.rows.filter(m=>m.nTaskBenchmarks>0).map(m=>m.name).sort(),[...new Set(r.models.map(m=>m.model_canonical))].sort());
 assert.equal(p.benchmarks,r.matched_benchmarks);
 for(const scenario of view.scenarios)for(const panel of scenario.panels){
  assert(panel.models.every(m=>m.evidence_kind===scenario.evidenceKind));
  assert(panel.entries.every(m=>m.evidence_kind===scenario.evidenceKind));
  const chart=V.taskData(r,panel.id);
  assert.deepEqual(V.modelPickerRows(chart).map(m=>m.name).sort(),panel.models.map(m=>m.model_canonical).sort());
  for(const m of panel.models)assert.equal(chart.rows.find(x=>x.name===m.model_canonical).score,m.publication_score);
 }
 assert.equal(JSON.stringify(r),before);
});
