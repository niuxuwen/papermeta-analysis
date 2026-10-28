const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib');
const site=__dirname+'/site/',manifest=JSON.parse(fs.readFileSync(site+'snapshot/manifest.json'));
const source=fs.readFileSync(site+'radar.js','utf8'),context={};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  function decodeSnapshot('),source.indexOf('  async function fetchSnapshotJSON(')),context);
const packed=Buffer.concat(manifest.parts.map(p=>fs.readFileSync(site+p.path)));
const snapshot=context.decodeSnapshot(JSON.parse(zlib.gunzipSync(packed)));
const V=require('./site/radar-viz.js');V.setModelRegistry(snapshot.model_registry);

test('v13 chart, table and CSV use the calibrated score and its own interval',()=>{
 const data=V.modelData(snapshot,'');const rows=new Map(data.rows.filter(r=>Number.isFinite(r.score)).map(r=>[r.name,r]));
 assert.equal(rows.size,132);
 for(const m of snapshot.index.models.filter(m=>!m.model_setting&&m.publication_eligible)){
  const r=rows.get(m.model_canonical),interval=V.barInterval(r);
  assert.equal(r.score,m.score);assert.equal(interval.center,m.score);
  assert.equal(interval.low,m.score_interval[0]);assert.equal(interval.high,m.score_interval[1]);
  assert.equal(interval.kind,'SCORE_INTERVAL');
 }
 const selected=new Set(['GPT-6-Sol','GPT-5.6-Sol']),csv=V.csv(data,selected);
 for(const n of selected)assert(csv.includes(String(rows.get(n).score)));
 assert(rows.get('GPT-6-Sol').score>rows.get('GPT-5.6-Sol').score);
 assert(rows.get('Claude 5.5 Opus').score>rows.get('Claude 5.5 Sonnet').score);
});

test('all published qualified same-vendor relations remain correctly ordered in chart data',()=>{
 const rows=new Map(V.modelData(snapshot,'').rows.filter(r=>Number.isFinite(r.score)).map(r=>[r.name,r]));let checked=0;
 for(const setting of snapshot.index.relative_reference_audit.settings){
  if(setting.model_setting)continue;
  for(const r of setting.consensus_projection.rules){assert(rows.get(r.winner).score>rows.get(r.loser).score);checked++;}
 }
 assert.equal(checked,109);
 assert.equal(new Set([...rows.values()].map(r=>r.score)).size,132);
});
