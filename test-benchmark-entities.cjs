const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const project=require('./benchmark-entity-projection.cjs'),V=require('./site/radar-viz.js');
test('real 23k-source registry preserves observations, scores and source identity without mixing variants',()=>{
 let raw,registry;
 if(fs.existsSync('validation/entity-projection-real-fixture.json')){
  raw=JSON.parse(fs.readFileSync('validation/entity-projection-real-fixture.json'));
  registry=JSON.parse(fs.readFileSync('validation/benchmark-entities-real-20261104.json'));
 }else{
  const zlib=require('node:zlib'),vm=require('node:vm'),{execFileSync}=require('node:child_process');
  const m=JSON.parse(fs.readFileSync('site/snapshot/current.json')),context={};vm.createContext(context);
  vm.runInContext(fs.readFileSync('site/snapshot-codec.js','utf8'),context);
  raw=context.decodeSnapshot(JSON.parse(zlib.gunzipSync(Buffer.concat(m.parts.map(p=>fs.readFileSync('site/'+p.path))))));
  const script='import sys,json;sys.path.insert(0,"backend");from benchmark_entities import build_registry;r=build_registry(json.load(sys.stdin));print(json.dumps(r))';
  registry={...JSON.parse(execFileSync('python',['-c',script],{input:JSON.stringify(raw.benchmarks),maxBuffer:64*1024*1024})),snapshot_id:raw.snapshot_id};
 }
 const before=JSON.stringify(raw),data=project(raw,registry);
 assert.equal(data.observations,raw.observations);assert.equal(data.index,raw.index);assert.equal(JSON.stringify(raw),before);
 const mappings=new Map(registry.mappings.map(m=>[JSON.stringify([m.paper_id,m.benchmark_id]),m]));
 for(const b of data.benchmarks){
  const m=mappings.get(JSON.stringify([b.paper_id,b.benchmark_id]));assert.equal(b.benchmark_entity_id,m.entity_id);
  if(m.status==='RESOLVED')for(const ref of V.directorySources(b))assert.equal(mappings.get(JSON.stringify([ref.paper_id,ref.benchmark_id])).variant_id,m.variant_id);
 }
 for(const name of ['MMLU','GSM8K','HumanEval']){
  const entity=registry.entities.find(e=>e.canonical_name===name);if(!entity)continue;assert(entity.sources.length>=1);
  const members=data.benchmarks.filter(b=>b.benchmark_entity_id===entity.entity_id);
  assert.equal(new Set(members.map(V.directoryKey)).size,1,name+' cross-paper directory fold');
 }
 const visible=V.visitorSnapshot(data);
 const old=V.visitorSnapshot(raw);
 assert.deepEqual(visible.observations,old.observations,'entity navigation does not admit or hide source scores');
 assert.equal(visible.index.models,old.index.models);
 console.log(JSON.stringify({source_records:data.benchmarks.length,entities:registry.statistics.resolved_entities,
  variants:registry.statistics.resolved_variants,pending:registry.statistics.unresolved_source_records,
  visible_directory_before:old.visitor_catalog_count,visible_directory_after:visible.visitor_catalog_count}));
});
test('descriptor mismatch and missing sources fail closed',()=>{
 const raw={snapshot_id:'a',benchmarks:[{paper_id:'p',benchmark_id:'b'}]};
 assert.throws(()=>project(raw,{snapshot_id:'b'}),/MISMATCH/);
 assert.throws(()=>project(raw,{snapshot_id:'a',mappings:[],variants:[]}),/INCOMPLETE/);
});
