const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),zlib=require('node:zlib'),V=require('./site/radar-viz.js');
const load=p=>JSON.parse(zlib.gunzipSync(fs.readFileSync(__dirname+'/validation/'+p)));
const evidence=load('task-comprehensive-task_evidence-20261101.json.gz'),meta=load('task-v11-measurements-real.json.gz');
V.setTaskMeasurements(meta);V.setModelRegistry(evidence.snapshot.model_registry);
for(const file of fs.readdirSync(__dirname+'/validation').filter(n=>/^task-v11-result-.*\.json.gz$/.test(n)))test('v11 source preview and result agree: '+file,()=>{
 const r=load(file).task_index,before=JSON.stringify(r),p=V.taskMatchPreview(evidence.snapshot,r.profile),v=V.taskOverview(r);
 const actual=[...new Set(r.models.map(m=>m.model_canonical))].sort(),predicted=p.rows.filter(m=>m.nTaskBenchmarks>0).map(m=>m.name).sort();
 assert.deepEqual(predicted,actual);assert.equal(p.benchmarks,r.matched_benchmarks);
 for(const scenario of v.scenarios)for(const panel of scenario.panels){
  assert(panel.models.every(m=>m.evidence_kind===scenario.evidenceKind));assert(panel.entries.every(m=>m.evidence_kind===scenario.evidenceKind));
  const chart=V.taskData(r,panel.id);assert.deepEqual(V.modelPickerRows(chart).map(r=>r.name).sort(),panel.models.map(m=>m.model_canonical).sort());
  for(const m of panel.models)assert.equal(chart.rows.find(r=>r.name===m.model_canonical).score,m.publication_score);
  if(scenario.evidenceKind==='UNVERIFIED_REFERENCE'){assert(chart.summaryLabel.includes('条件待核'));assert(chart.note.includes('不表示模型已满足任务要求'));assert(panel.models.every(m=>!m.task_eligible));}
 }
 assert.equal(JSON.stringify(r),before);
});
test('v11 exact input mode menu and explicit pending-evidence section are present',()=>{
 const html=fs.readFileSync(__dirname+'/site/index.html','utf8'),js=fs.readFileSync(__dirname+'/site/radar.js','utf8');
 for(const mode of ['image','audio','video','audio+video'])assert(html.includes('value="'+mode+'"'));
 assert(js.includes("['UNVERIFIED_REFERENCE','条件待核的来源参考'"));
});
