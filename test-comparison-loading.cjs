const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib'),{webcrypto}=require('node:crypto'),V=require('./site/radar-viz.js');
const root=__dirname+'/site/',m=JSON.parse(fs.readFileSync(root+'snapshot/current.json')),index=JSON.parse(fs.readFileSync(root+m.comparisons.path));
const decoder={};vm.createContext(decoder);vm.runInContext(fs.readFileSync(root+'snapshot-codec.js','utf8'),decoder);
const full=V.visitorSnapshot(decoder.decodeSnapshot(JSON.parse(zlib.gunzipSync(Buffer.concat(m.parts.map(p=>fs.readFileSync(root+p.path)))))));
function setup(prefix){
  const base='https://viewer.test'+prefix,seen=[],bootstrap=fs.readFileSync(root+'index.html','utf8').match(/<script id="snapshot-bootstrap" type="application\/json">([\s\S]*?)<\/script>/)[1];
  let fail=0,tamper=false;
  const context={URL,Request,Response,Blob,DecompressionStream,TextEncoder,TextDecoder,Uint8Array,DOMException,AbortController,setTimeout,clearTimeout,crypto:webcrypto,console,
    location:{href:base},document:{currentScript:{src:base+'snapshot-adapter.js'},readyState:'loading',addEventListener(){},getElementById:()=>({textContent:bootstrap})},
    window:{fetch:async(input,options)=>{const u=new URL(input);assert(u.pathname.startsWith(prefix));const p=u.pathname.slice(prefix.length);seen.push(p);
      if(p===index.parts[0].path&&fail-->0)throw new TypeError('connection interrupted');
      return new Response(tamper&&p===index.parts[0].path?Buffer.from('bad'):fs.readFileSync(root+p));}}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(root+'snapshot-adapter.js','utf8'),context);
  return {context,seen,fail:n=>{fail=n;},tamper:value=>{tamper=value;}};
}
for(const prefix of ['/','/papermeta-analysis/'])test('comparison uses small verified parts and preserves every original group at '+prefix,async()=>{
  const s=setup(prefix),progress=[],data=await s.context.window.RadarLoadComparison({onProgress:text=>progress.push(text)});
  assert.equal(data.comparison_loaded,true);assert.equal(data.sources_loaded,false);
  assert.deepEqual(JSON.parse(JSON.stringify(data.index.groups)),JSON.parse(JSON.stringify(full.index.groups)));
  assert.deepEqual(JSON.parse(JSON.stringify(data.capability_annotations)),JSON.parse(JSON.stringify(full.capability_annotations)));
  assert(index.parts.every(p=>p.bytes<=262144));assert(index.bytes<2500000);
  assert(!s.seen.some(p=>m.parts.some(part=>part.path===p)));assert(progress.some(t=>t.includes('100%')));
  V.setModelRegistry(full.model_registry);
  for(const [left,right]of [['GPT-6-Sol','GPT-5.6-Sol'],['GPT-5.2','GPT-5.4'],['Claude 5 Opus','Claude 5 Sonnet'],['Gemini 3.1 Pro','Gemini 3.8 Flash']]){
    for(const method of ['pairedSources','commonSourceEvidence','pairedBenchmarkAxes'])assert.deepEqual(JSON.parse(JSON.stringify(V[method](data,'',left,right))),JSON.parse(JSON.stringify(V[method](full,'',left,right))),method);
    const caps=full.capability_atlas.capabilities.map(c=>({id:c.id,label:c.label||c.id}));
    assert.deepEqual(JSON.parse(JSON.stringify(V.capabilityRadarData(data,'',left,right,caps))),JSON.parse(JSON.stringify(V.capabilityRadarData(full,'',left,right,caps))));
  }
  const benches=new Map(full.benchmarks.map(b=>[JSON.stringify([b.paper_id,b.benchmark_id]),b]));
  for(const g of full.index.groups.slice(0,30)){
    const b=benches.get(JSON.stringify([g.paper_id,g.benchmark_id]));
    assert.equal(V.csv(V.visitorChartData(V.sourceGroupData(data,b,g))),V.csv(V.visitorChartData(V.sourceGroupData(full,b,g))));
  }
  const count=s.seen.length;await s.context.window.RadarLoadComparison();assert.equal(s.seen.length,count);
});
test('one interrupted part retries locally without restarting the entire archive',async()=>{
  const s=setup('/');s.fail(1);await s.context.window.RadarLoadComparison();
  assert.equal(s.seen.filter(p=>p===index.parts[0].path).length,2);
  assert(!s.seen.some(p=>m.parts.some(part=>part.path===p)));
});
test('tampered part fails integrity checks and a later attempt can recover',async()=>{
  const s=setup('/');s.tamper(true);await assert.rejects(s.context.window.RadarLoadComparison(),/COMPARISON_INTEGRITY_FAILURE/);
  s.tamper(false);assert.equal((await s.context.window.RadarLoadComparison()).comparison_loaded,true);
});
test('exhausted part requests are bounded and retry remains possible',async()=>{
  const s=setup('/');s.fail(3);await assert.rejects(s.context.window.RadarLoadComparison(),/connection interrupted/);
  assert.equal(s.seen.filter(p=>p===index.parts[0].path).length,3);
  assert.equal((await s.context.window.RadarLoadComparison()).comparison_loaded,true);
});
test('the actual source-view fetch uses comparison data and never the bulk loader',async()=>{
  const s=setup('/');s.context.window.RadarLoadWorkspace=()=>{throw Error('Bulk archive must not load');};
  Object.assign(s.context,{validate:x=>x,decodeSnapshot:x=>x,$:()=>({}),state:{}});
  const code=fs.readFileSync(root+'radar.js','utf8');vm.runInContext(code.slice(code.indexOf('  async function fetchSnapshotJSON('),code.indexOf('  function setLoadingUI(')),s.context);
  assert.equal((await s.context.fetchSnapshotJSON('api/workspace',10000)).comparison_loaded,true);
});
