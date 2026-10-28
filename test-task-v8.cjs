const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib');
const site=__dirname+'/site/',manifest=JSON.parse(fs.readFileSync(site+'snapshot/manifest.json'));
const radar=fs.readFileSync(site+'radar.js','utf8'),context={};vm.createContext(context);
vm.runInContext(radar.slice(radar.indexOf('  function decodeSnapshot('),radar.indexOf('  async function fetchSnapshotJSON(')),context);
const packed=Buffer.concat(manifest.parts.map(p=>fs.readFileSync(site+p.path)));
const raw=context.decodeSnapshot(JSON.parse(zlib.gunzipSync(packed)));
const V=require('./site/radar-viz.js');V.setModelRegistry(raw.model_registry);
const snapshot=V.visitorSnapshot(raw);
const report=JSON.parse(fs.readFileSync(__dirname+'/validation/task-score-v8-multidomain.json'));
const measurements=JSON.parse(fs.readFileSync(__dirname+'/validation/task-measurements-v8-real.json'));

for(const [name,result]of Object.entries(report.profiles))test('real v8 candidate preview agrees with backend: '+name,()=>{
 assert.equal(measurements.snapshot_id,manifest.snapshot_id);V.setTaskMeasurements(measurements);
 try{
  const preview=V.taskMatchPreview(snapshot,result.profile);
  assert.equal(preview.benchmarks,result.matched_benchmarks);
  for(const c of result.capabilities)assert.equal(preview.capabilities.find(x=>x.id===c.capability_id).nBenchmarks,c.n_benchmarks);
  assert.equal(preview.rows.filter(r=>r.nTaskBenchmarks>0).length,result.models);
 }finally{V.setTaskMeasurements(null);}
});

test('v8 frontend source guard retains scoped aliases and rejects the percent outlier',()=>{
 assert.equal(measurements.groups['9347c87fa771778b13d45bd4'].aliases.Captioner,'Qwen 3 Omni Captioner');
 assert(measurements.groups['af400fb19cadf4554a0b2a62'].excluded.some(s=>s.reason==='source_value_outside_declared_percentage'));
});
