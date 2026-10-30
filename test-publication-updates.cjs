const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib');
const {webcrypto,createHash}=require('node:crypto');
const site=__dirname+'/site/',current=JSON.parse(fs.readFileSync(site+'snapshot/current.json'));
const original=JSON.parse(zlib.gunzipSync(fs.readFileSync(site+current.ranking.path)));
function setup(prefix='/',sameId=false){
 const seen=[],next=structuredClone(current),light=structuredClone(original);
 next.snapshot_id=light.snapshot_id=sameId?current.snapshot_id:'aaaaaaaaaaaaaaaaaaaaaaaa';next.generated_at=light.generated_at='2026-10-30T09:00:00Z';
 const raw=zlib.gzipSync(JSON.stringify(light));
 next.ranking={snapshot_id:next.snapshot_id,path:'snapshot/'+next.snapshot_id+'/ranking-test.json.gz',bytes:raw.length,sha256:createHash('sha256').update(raw).digest('hex')};
 let manifest=next,corrupt=false;
 const boot=JSON.stringify({manifest:current,snapshot:{snapshot_id:current.snapshot_id}});
 const c={URL,Request,Response,Blob,DecompressionStream,TextEncoder,TextDecoder,Uint8Array,DOMException,crypto:webcrypto,console,
  document:{currentScript:{src:'https://viewer.test'+prefix+'snapshot-adapter.js'},readyState:'loading',addEventListener(){},getElementById:()=>({textContent:boot})},
  location:{href:'https://viewer.test'+prefix},window:{fetch:async input=>{
    const u=new URL(input);assert(u.pathname.startsWith(prefix));const path=u.pathname.slice(prefix.length);seen.push(path);
    if(path==='snapshot/current.json')return Response.json(manifest);
    if(path===next.ranking.path)return new Response(corrupt?'broken':raw);
    return new Response(fs.readFileSync(site+path));
  }}};
 vm.createContext(c);vm.runInContext(fs.readFileSync(site+'snapshot-adapter.js','utf8'),c);
 return {c,next,seen,manifest(value){manifest=value;},corrupt(value){corrupt=value;}};
}
for(const prefix of ['/','/papermeta-analysis/'])test('new publication verifies before switching the entire generation at '+prefix,async()=>{
 const s=setup(prefix),w=s.c.window;
 assert.equal((await w.RadarLoadRanking()).snapshot_id,current.snapshot_id);
 const pending=await w.RadarCheckPublication();assert.equal(pending.snapshot.snapshot_id,s.next.snapshot_id);
 assert.equal((await w.RadarLoadRanking()).snapshot_id,current.snapshot_id,'not installed before commit');
 pending.commit();assert.equal((await w.RadarLoadRanking()).snapshot_id,s.next.snapshot_id);
 assert.equal(w.RadarHomeSnapshot.snapshot_id,s.next.snapshot_id);
 assert.equal(await w.RadarCheckPublication(),null);assert.equal(s.seen.filter(p=>p===s.next.ranking.path).length,1);
});
test('unchanged version checks one small no-store descriptor and no archive',async()=>{
 const s=setup();s.manifest(current);assert.equal(await s.c.window.RadarCheckPublication(),null);
 assert.deepEqual(s.seen,['snapshot/current.json']);
});
test('rebuilt assets are detected even if the underlying evidence id is unchanged',async()=>{
 const s=setup('/',true),pending=await s.c.window.RadarCheckPublication();assert(pending);
 pending.commit();assert.equal((await s.c.window.RadarLoadRanking()).generated_at,s.next.generated_at);
});
test('corrupt or incomplete publication leaves the verified version usable and retryable',async()=>{
 const s=setup();s.corrupt(true);await assert.rejects(s.c.window.RadarCheckPublication(),/INTEGRITY/);
 assert.equal((await s.c.window.RadarLoadRanking()).snapshot_id,current.snapshot_id);
 s.corrupt(false);assert((await s.c.window.RadarCheckPublication()).snapshot);
});
test('a stale CDN response cannot roll the page back to older data',async()=>{
 const s=setup();s.manifest({...s.next,generated_at:'2020-01-01T00:00:00Z'});
 await assert.rejects(s.c.window.RadarCheckPublication(),/INVALID_PUBLICATION/);
 assert.equal((await s.c.window.RadarLoadRanking()).snapshot_id,current.snapshot_id);
});
test('open dialogs, background pages and task editing defer automatic changes',async()=>{
 const code=fs.readFileSync(site+'radar.js','utf8'),start=code.indexOf('  let publicationUpdating='),end=code.indexOf('  function refresh(options=',start);
 let probes=0;const state={loading:false,view:'models'},doc={hidden:false,querySelector:()=>false};
 const c={window:{RadarCheckPublication:async()=>{probes++;return null;}},state,document:doc,refreshInFlight:null,AbortController,setTimeout,clearTimeout};
 vm.createContext(c);vm.runInContext(code.slice(start,end),c);
 doc.hidden=true;await c.checkPublishedUpdate();assert.equal(probes,0);
 doc.hidden=false;doc.querySelector=()=>true;await c.checkPublishedUpdate();assert.equal(probes,0);
 doc.querySelector=()=>false;state.view='tasks';await c.checkPublishedUpdate();assert.equal(probes,0);
 state.view='models';await c.checkPublishedUpdate();assert.equal(probes,1);
});
