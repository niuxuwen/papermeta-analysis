const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib');
const manifest=JSON.parse(fs.readFileSync(__dirname+'/site/snapshot/manifest.json'));
const source=fs.readFileSync(__dirname+'/site/radar.js','utf8'),ctx={};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function decodeSnapshot('),source.indexOf('  async function fetchSnapshotJSON(')),ctx);
const raw=ctx.decodeSnapshot(JSON.parse(zlib.gunzipSync(Buffer.concat(manifest.parts.map(p=>fs.readFileSync(__dirname+'/site/'+p.path))))));
const V=require('./site/radar-viz.js'),snapshot=V.visitorSnapshot(raw),left='GPT-6-Sol',right='GPT-5.6-Sol';
test('real common sources expose all final-performance metrics separately from the fit',()=>{
 const r=V.commonSourceEvidence(snapshot,'',left,right);
 assert.equal(r.paperFamilies,2);assert.equal(r.benchmarks,2);assert.equal(r.sourceGroups,16);
 assert.deepEqual(r.paperWins,{left:2,tie:0,right:0});assert.equal(r.excluded.nonFinal,1);
 assert.deepEqual(r.papers.map(p=>p.metricWins),[{left:9,tie:0,right:2},{left:4,tie:1,right:0}]);
 assert.deepEqual(r.rows.filter(x=>x.metric==='%').map(x=>x.sourceCoordinate),['表 22 · 原表列索引 2','表 22 · 原表列索引 4']);
 assert.equal(r.papers.reduce((n,p)=>n+p.rows.length,0),r.rows.length);
 for(const row of r.rows){
  const g=snapshot.index.groups.find(g=>g.group_id===row.group);
  assert.equal(row.left,g.scores.find(s=>s.model_canonical===left).value_numeric);
  assert.equal(row.right,g.scores.find(s=>s.model_canonical===right).value_numeric);
  assert.equal(g.metric_role,'PERFORMANCE');assert.equal(g.global_status,'CORE_READY');
 }
});
test('swapping models reverses direct evidence without changing source membership',()=>{
 const a=V.commonSourceEvidence(snapshot,'',left,right),b=V.commonSourceEvidence(snapshot,'',right,left);
 assert.deepEqual(a.rows.map(r=>r.group),b.rows.map(r=>r.group));
 assert.equal(a.paperWins.left,b.paperWins.right);assert.equal(a.paperWins.right,b.paperWins.left);
 for(let i=0;i<a.papers.length;i++)assert(Math.abs(a.papers[i].winFraction+b.papers[i].winFraction-1)<1e-12);
});
test('duplicate real cells do not create independent support',()=>{
 const original=V.commonSourceEvidence(snapshot,'',left,right);
 const gs=snapshot.index.groups.filter(g=>original.rows.some(r=>r.group===g.group_id));
 const s={benchmarks:snapshot.benchmarks,index:{groups:[...gs,...gs]}};
 const r=V.commonSourceEvidence(s,'',left,right);
 assert.equal(r.sourceGroups,original.sourceGroups);assert.equal(r.paperFamilies,2);
 assert.equal(r.excluded.duplicate,16);
});
test('manufacturer labels, fitted ranks and display selection do not affect direct comparisons',()=>{
 const before=V.commonSourceEvidence(snapshot,'',left,right);
 const s={benchmarks:snapshot.benchmarks,index:{groups:snapshot.index.groups,models:[]},model_registry:{models:[]}};
 assert.deepEqual(V.commonSourceEvidence(s,'',left,right),before);
 V.setModelRegistry({models:[{canonical_name:left,vendor:'Changed vendor'},{canonical_name:right,vendor:'Another vendor'}]});
 assert.deepEqual(V.commonSourceEvidence(s,'',left,right),before);
 V.setModelRegistry(snapshot.model_registry);
});
test('no common measurements and identical selections remain empty',()=>{
 assert.equal(V.commonSourceEvidence(snapshot,'',left,left).sourceGroups,0);
 assert.equal(V.commonSourceEvidence(snapshot,'','Absent model',right).paperFamilies,0);
 assert.equal(V.commonSourceEvidence(snapshot,'unseen experimental setting',left,right).sourceGroups,0);
});
