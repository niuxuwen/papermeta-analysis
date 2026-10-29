const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib'),V=require('./site/radar-viz.js');
const root=__dirname+'/site/',m=JSON.parse(fs.readFileSync(root+'snapshot/current.json'));
const light=JSON.parse(zlib.gunzipSync(fs.readFileSync(root+m.ranking.path))),ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(root+'snapshot-codec.js','utf8'),ctx);
const full=V.visitorSnapshot(ctx.decodeSnapshot(JSON.parse(zlib.gunzipSync(Buffer.concat(m.parts.map(p=>fs.readFileSync(root+p.path)))))));
const source=fs.readFileSync(root+'radar.js','utf8'),identity=b=>`${b.paper_id}\0${b.benchmark_id}`,plain=x=>JSON.parse(JSON.stringify(x));
function runtime(snapshot){
  const context={state:{snapshot,domain:'',taskType:'',capability:'',eligibility:'ELIGIBLE',query:''},annotationItems:()=>snapshot.capability_annotations?.items||[],Viz:V,identity};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  function benchTags('),source.indexOf('  function taskMessage(')),context);
  vm.runInContext(source.slice(source.indexOf('  function visibleBenchmarks('),source.indexOf('  let uiReady=')),context);
  const originalTags=context.benchTags,cache=new Map();
  context.benchTags=(row,layer)=>{const key=identity(row)+'\0'+layer;if(!cache.has(key))cache.set(key,originalTags(row,layer));return cache.get(key);};
  return context;
}
const a=runtime(full),b=runtime(light);
test('all real directory labels, aliases, merged identities and counts survive lightweight loading',()=>{
  assert.equal(light.catalog_loaded,true);assert.equal(light.benchmarks.length,full.benchmarks.length);
  const rows=new Map();for(const row of full.observations){const k=identity(row);if(!rows.has(k))rows.set(k,[]);rows.get(k).push(row);}
  for(let i=0;i<full.benchmarks.length;i++){
    const original=full.benchmarks[i],compact=light.benchmarks[i];
    assert.equal(identity(compact),identity(original));assert.equal(V.directoryKey(compact),V.directoryKey(original));
    assert.deepEqual(plain(V.directorySources(compact).map(identity)),plain(V.directorySources(original).map(identity)));
    for(const layer of ['domains','tasks','capabilities'])assert.deepEqual(plain(b.benchTags(compact,layer)),plain(a.benchTags(original,layer)),original.benchmark_name+' '+layer);
    const obs=V.directorySources(original).flatMap(ref=>rows.get(identity(ref))||[]);
    const expected={observations:obs.length,models:new Set(obs.map(r=>r.model_canonical).filter(Boolean)).size,tables:new Set(obs.filter(r=>r.table_id!=null).map(r=>JSON.stringify([r.paper_id,r.table_id]))).size};
    assert.deepEqual(V.directoryStats(light,compact),expected,original.benchmark_name);
  }
  assert(light.benchmarks.some(x=>x.catalog_display_tags.capabilities.length));
  assert(light.benchmarks.some(x=>x.catalog_display_stats.observations>0));
});
test('catalogue filtering and ordering match the full source across labels, combinations and search',()=>{
  const verify=filter=>{
    Object.assign(a.state,{domain:'',taskType:'',capability:'',eligibility:'ELIGIBLE',query:''},filter);
    Object.assign(b.state,{domain:'',taskType:'',capability:'',eligibility:'ELIGIBLE',query:''},filter);
    assert.deepEqual(plain(b.visibleBenchmarks().map(identity)),plain(a.visibleBenchmarks().map(identity)),JSON.stringify(filter));
  };
  verify({});verify({eligibility:'all'});verify({query:'Rynn'});verify({query:'LOOM'});verify({query:'not-a-real-benchmark'});
  for(const [field,layer]of [['domain','domains'],['taskType','tasks'],['capability','capabilities']]){
    for(const value of new Set(full.benchmarks.flatMap(x=>a.benchTags(x,layer))))verify({[field]:value});
  }
  const checked=new Set();for(const row of full.benchmarks){
    const domain=a.benchTags(row,'domains')[0],taskType=a.benchTags(row,'tasks')[0],capability=a.benchTags(row,'capabilities')[0];
    const key=JSON.stringify([domain,taskType,capability]);if(domain&&taskType&&capability&&!checked.has(key)){checked.add(key);verify({domain,taskType,capability});}
  }
});
test('capability map keeps every real coverage total and attribution',()=>{
  assert.deepEqual(light.capability_atlas,plain(full.capability_atlas));
  const fields=['group_id','paper_id','benchmark_id','status','capabilities','domains','tasks'];
  const expected=(full.capability_annotations.items||[]).map(x=>Object.fromEntries(fields.filter(k=>k in x).map(k=>[k,x[k]])));
  assert.deepEqual(light.capability_annotations.items,plain(expected));
});
test('unloaded data stays pending rather than becoming zero achievements',()=>{
  assert.deepEqual(V.directoryStats({detail_loaded:true,sources_loaded:false,observations:[]},full.benchmarks[0]),{observations:null,models:null,tables:null});
});
test('task evidence does not mistake the compact ranking for complete candidate evidence',()=>{
  const c={state:{snapshot:light},taskState:{}};vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('  function taskEvidenceSnapshot('),source.indexOf('  let taskEvidenceInFlight')),c);
  assert.equal(c.taskEvidenceSnapshot(),null);
  c.taskState.evidenceSnapshot={realTaskEvidence:true};assert.equal(c.taskEvidenceSnapshot(),c.taskState.evidenceSnapshot);
  c.state.snapshot=full;assert.equal(c.taskEvidenceSnapshot(),full);
});
test('navigation reuses a complete light catalogue without requesting the full source archive',()=>{
  const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{setAttribute(){}});return nodes.get(id);},calls=[];
  const c={state:{snapshot:light,view:'models'},visitorEdition:true,window:{RadarHomeSnapshot:{},scrollTo(){}},history:{replaceState(){}},document:{querySelectorAll:()=>[]},$:node,render(){},refresh:x=>calls.push(x),loadTaskEvidenceForPreview:()=>Promise.resolve(),taskMessage(){}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('  let uiReady='),source.indexOf('  function sourceLabel(')),c);vm.runInContext('uiReady=true',c);
  c.setView('benchmarks');c.setView('capabilities');c.setView('models');assert.deepEqual(calls,[]);
});
