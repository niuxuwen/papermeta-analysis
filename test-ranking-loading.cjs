const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib');
const {webcrypto,createHash}=require('node:crypto'),V=require('./site/radar-viz.js');
const root=__dirname+'/site/',m=JSON.parse(fs.readFileSync(root+'snapshot/current.json'));
const bytes=fs.readFileSync(root+m.ranking.path),light=JSON.parse(zlib.gunzipSync(bytes));
const decoder={};vm.createContext(decoder);vm.runInContext(fs.readFileSync(root+'snapshot-codec.js','utf8'),decoder);
const full=V.visitorSnapshot(decoder.decodeSnapshot(JSON.parse(zlib.gunzipSync(Buffer.concat(m.parts.map(p=>fs.readFileSync(root+p.path)))))));
V.setModelRegistry(full.model_registry);
test('all real settings preserve exact ranking rows, chart values and visitor exports',()=>{
  assert.equal(light.snapshot_id,full.snapshot_id);assert.equal(light.sources_loaded,false);
  assert.equal(bytes.length,m.ranking.bytes);assert.equal(createHash('sha256').update(bytes).digest('hex'),m.ranking.sha256);
  assert(bytes.length<400000);assert(bytes.length<m.parts.reduce((n,p)=>n+p.bytes,0)*0.04);
  assert.deepEqual(V.settings(light),V.settings(full));
  for(const setting of V.settings(full)){
    const expected=V.visitorChartData(V.modelData(full,setting)),actual=V.modelData(light,setting);
    // JSON-normalize omitted optional properties across wire serialization.
    assert.deepEqual(actual.rows,JSON.parse(JSON.stringify(expected.rows)),setting);
    assert.deepEqual(actual.axes,JSON.parse(JSON.stringify(expected.axes)),setting);
    assert.equal(V.csv(actual),V.csv(expected),setting+' CSV');
    assert.equal(V.sourceCsv(actual),V.sourceCsv(expected),setting+' source CSV');
  }
});
function setup(prefix){
  const seen=[],base='https://viewer.test'+prefix,bootstrap=fs.readFileSync(root+'index.html','utf8').match(/<script id="snapshot-bootstrap" type="application\/json">([\s\S]*?)<\/script>/)[1];
  let corrupt=false;
  const context={URL,Request,Response,Blob,DecompressionStream,TextEncoder,TextDecoder,Uint8Array,DOMException,crypto:webcrypto,console,
    location:{href:base},document:{currentScript:{src:base+'snapshot-adapter.js'},readyState:'loading',addEventListener(){},getElementById:()=>({textContent:bootstrap})},
    window:{fetch:async input=>{const url=new URL(input);assert(url.pathname.startsWith(prefix));seen.push(url.pathname);const data=fs.readFileSync(root+url.pathname.slice(prefix.length));return new Response(corrupt?Buffer.from('corrupt'):data);}}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(root+'snapshot-adapter.js','utf8'),context);
  return {context,seen,corrupt(value){corrupt=value;}};
}
for(const prefix of ['/','/papermeta-analysis/'])test('model chart loads one small verified asset and no archive at '+prefix,async()=>{
  const s=setup(prefix),d=await s.context.window.RadarLoadRanking();
  assert.equal(d.snapshot_id,m.snapshot_id);assert.equal(s.seen.length,1);assert(s.seen[0].includes('ranking-'));
  await s.context.window.RadarLoadRanking();assert.equal(s.seen.length,1);
});
test('corrupted ranking data fails closed and can be retried',async()=>{
  const s=setup('/');s.corrupt(true);await assert.rejects(s.context.window.RadarLoadRanking(),/RANKING_INTEGRITY_FAILURE/);
  s.corrupt(false);assert.equal((await s.context.window.RadarLoadRanking()).snapshot_id,m.snapshot_id);
});
test('model-page refresh uses the compact loader; explicit source request uses the archive',async()=>{
  const s=setup('/'),code=fs.readFileSync(root+'radar.js','utf8'),node={},calls=[];
  Object.assign(s.context,{AbortController,setTimeout,clearTimeout,state:{snapshot:null,loading:false,view:'models'},requestedModel:null,lastRefreshAt:0,
    $:()=>node,setLoadingUI(){},renderReferences(){},date:x=>x,validate:x=>x,render(){},resumeInteractive(){},Viz:{setModelRegistry(){}},taskState:{confirmed:false},
    fetchSnapshotJSON:async()=>{calls.push('archive');return full;}});
  s.context.window.RadarHomeSnapshot={...light,detail_loaded:false};
  vm.runInContext(code.slice(code.indexOf('  let refreshInFlight='),code.indexOf("  for(const btn of document.querySelectorAll('[data-view]'))")),s.context);
  await s.context.refresh();assert.equal(calls.length,0);assert.equal(s.context.state.snapshot.sources_loaded,false);
  await s.context.refresh({details:true});assert.deepEqual(calls,['archive']);assert.notEqual(s.context.state.snapshot.sources_loaded,false);
});
