const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib');
const site=__dirname+'/site/',manifest=JSON.parse(fs.readFileSync(site+'snapshot/manifest.json'));
const source=fs.readFileSync(site+'radar.js','utf8'),context={};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  function decodeSnapshot('),source.indexOf('  async function fetchSnapshotJSON(')),context);
const packed=Buffer.concat(manifest.parts.map(p=>fs.readFileSync(site+p.path)));
const snapshot=context.decodeSnapshot(JSON.parse(zlib.gunzipSync(packed)));
const V=require('./site/radar-viz.js');V.setModelRegistry(snapshot.model_registry);

test('v14 chart and export use the unprojected fitted score and matching interval',()=>{
 const rows=new Map(V.modelData(snapshot,'').rows.filter(r=>Number.isFinite(r.score)).map(r=>[r.name,r]));
 assert.equal(rows.size,132);assert.equal(snapshot.index.method.version,14);
 for(const m of snapshot.index.models.filter(m=>!m.model_setting&&m.publication_eligible)){
  const r=rows.get(m.model_canonical),interval=V.barInterval(r);
  assert.equal(r.score,m.score);assert.equal(m.score,Math.round(m.base_publication_score*1e6)/1e6);
  assert.equal(interval.center,m.score);assert.equal(interval.low,m.score_interval[0]);assert.equal(interval.high,m.score_interval[1]);
  assert.equal(m.source_consensus,null);
 }
 const data=V.modelData(snapshot,''),selected=new Set(['GPT-6-Sol','GPT-5.6-Sol']);
 const csv=V.csv(data,selected);for(const name of selected)assert(csv.includes(String(rows.get(name).score)));
});

test('v14 has no hidden vendor constraints and preserves all original evidence',()=>{
 assert.equal(snapshot.index.method.hard_order_projection,false);
 assert.equal(snapshot.index.method.vendor_consistency.enabled,false);
 for(const s of snapshot.index.relative_reference_audit.settings){assert.equal(s.consensus_projection.enabled,false);assert.equal(s.consensus_projection.constraints,0);}
 assert.equal(snapshot.observations.length,30594);
 assert.equal(snapshot.index.source_context_audit.measurement_roles.length,9);
 assert.equal(snapshot.index.source_context_audit.conditions.length,15);
 const groups=new Map(snapshot.index.groups.map(g=>[g.group_id,g]));
 for(const r of snapshot.index.source_context_audit.measurement_roles)assert.notEqual(groups.get(r.group_id).global_status,'CORE_READY');
});
