/* The deployment gate compares derived pages with the exact published source. */
'use strict';
const fs=require('node:fs'),zlib=require('node:zlib'),assert=require('node:assert/strict'),vm=require('node:vm');
const {createHash}=require('node:crypto'),V=require('./site/radar-viz.js');
const m=JSON.parse(fs.readFileSync('site/snapshot/current.json'));
const report=JSON.parse(fs.readFileSync(process.argv[2]));
assert.equal(m.snapshot_id,report.snapshot_id);assert.equal(m.observations,report.observations);
const packed=Buffer.concat(m.parts.map(p=>fs.readFileSync('site/'+p.path)));
assert.equal(createHash('sha256').update(packed).digest('hex'),m.workspace_sha256);
const ctx={};vm.createContext(ctx);vm.runInContext(fs.readFileSync('site/snapshot-codec.js','utf8'),ctx);
const full=ctx.decodeSnapshot(JSON.parse(zlib.gunzipSync(packed))),pub=V.visitorSnapshot(full);
assert.equal(full.observations.length,report.observations);assert.equal(full.index.method.version,15);
const read=meta=>{const raw=fs.readFileSync('site/'+meta.path);assert.equal(raw.length,meta.bytes);assert.equal(createHash('sha256').update(raw).digest('hex'),meta.sha256);return JSON.parse(zlib.gunzipSync(raw));};
const light=read(m.ranking);assert.equal(light.snapshot_id,m.snapshot_id);
V.setModelRegistry(pub.model_registry);
for(const setting of V.settings(pub)){
 const expected=V.visitorChartData(V.modelData(pub,setting)),actual=V.modelData(light,setting);
 assert.deepEqual(actual.rows,JSON.parse(JSON.stringify(expected.rows)));
 assert.deepEqual(actual.axes,JSON.parse(JSON.stringify(expected.axes)));
 assert.equal(V.csv(actual),V.csv(expected));
}
const sources=new Map();for(const row of pub.observations){const k=JSON.stringify([row.paper_id,row.benchmark_id]);if(!sources.has(k))sources.set(k,[]);sources.get(k).push(row);}
for(const b of light.benchmarks){
 const rows=V.directorySources(b).flatMap(r=>sources.get(JSON.stringify([r.paper_id,r.benchmark_id]))||[]);
 assert.equal(V.directoryStats(light,b).observations,rows.length);
}
const index=read(m.model_details),names=Object.keys(index.models);
for(const name of names.filter((_,i)=>i===0||i===names.length-1||i===Math.floor(names.length/2))){
 const d=read(index.models[name]);assert.equal(d.snapshot_id,m.snapshot_id);
 assert.deepEqual(d.observations,JSON.parse(JSON.stringify(pub.observations.filter(r=>r.model_canonical===name))));
}
const html=fs.readFileSync('site/index.html','utf8'),boot=JSON.parse(html.match(/<script id="snapshot-bootstrap" type="application\/json">([\s\S]*?)<\/script>/)[1]);
assert.equal(boot.manifest.snapshot_id,m.snapshot_id);
assert(!fs.existsSync('site/backend'));
console.log(JSON.stringify({snapshot_id:m.snapshot_id,observations:full.observations.length,models:names.length,
 settings:V.settings(pub).length,rankings:'exact',catalog_counts:'exact',model_sources:'exact',model_calls:0}));
