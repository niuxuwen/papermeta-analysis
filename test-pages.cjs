const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const site=__dirname+'/site/',source=fs.readFileSync(site+'snapshot-adapter.js','utf8'),report=JSON.parse(fs.readFileSync(__dirname+'/publication-validation.json','utf8'));
const manifest=JSON.parse(fs.readFileSync(site+'snapshot/manifest.json','utf8'));
function setup(prefix){
 const seen=[],home='https://viewer.test'+prefix;
 const original=async(input,options)=>{const u=new URL(String(input));assert(u.pathname.startsWith(prefix),'Request escaped the GitHub Pages project path');seen.push([u.pathname,options?.cache]);return new Response(fs.readFileSync(site+u.pathname.slice(prefix.length)));};
 const context={URL,Request,Response,Blob,DecompressionStream,TextDecoder,TextEncoder,Uint8Array,Array,DOMException,crypto:webcrypto,console,location:{href:home},document:{currentScript:{src:home+'snapshot-adapter.js'},readyState:'loading',addEventListener(){}},window:{fetch:original}};
 vm.createContext(context);vm.runInContext(source,context);
 return {fetch:context.window.fetch,context,seen,home};
}
for(const prefix of ['/','/papermeta-analysis/'])test('real snapshot and source details work at '+prefix,async()=>{
 const s=setup(prefix),r=await s.fetch(s.home+'api/workspace');assert.equal(r.status,200);const wire=await r.json();
 const code=fs.readFileSync(site+'radar.js','utf8');vm.runInContext(code.slice(code.indexOf('  function decodeSnapshot('),code.indexOf('  async function fetchSnapshotJSON(')),s.context);
 const data=s.context.decodeSnapshot(wire);assert.equal(data.observations.length,report.observations);assert.equal(data.index.method.version,11);assert.equal(data.index.method.hard_order_projection,false);
 const published=data.index.models.filter(m=>!m.model_setting&&m.publication_eligible);assert.equal(published.length,report.published_default_models);for(const m of published)assert.equal(m.score,report.published_default_model_scores[m.model_canonical]);
 const overview=await s.fetch(s.home+'api/overview');assert.equal(overview.status,200);assert.equal((await overview.json()).generated_at,manifest.generated_at);
 const pair=JSON.parse(Object.keys(manifest.details)[0]),q=new URLSearchParams({paper_id:pair[0],benchmark_id:pair[1]});
 const detail=await (await s.fetch(s.home+'api/benchmark?'+q)).json();assert.equal(detail.benchmark.paper_id,pair[0]);assert.equal(detail.benchmark.benchmark_id,pair[1]);
 assert.equal(s.seen.find(r=>r[0].endsWith('/snapshot/current.json'))[1],'no-store');
 assert.equal((await s.fetch(s.home+'api/task-profile',{method:'POST'})).status,403);
});

test('home includes exact real scores before scripts or archive downloads',()=>{
 const html=fs.readFileSync(site+'index.html','utf8');
 const bootstrap=JSON.parse(html.match(/<script id="snapshot-bootstrap" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const expected=Object.entries(report.published_default_model_scores).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).slice(0,6);
 assert.deepEqual(bootstrap.snapshot.home_summary.models.map(m=>[m.name,m.score]),expected);
 for(const [name,score]of expected){assert(html.includes('data-home-model="'+name+'"'));assert(html.includes(score.toLocaleString('zh-CN',{maximumFractionDigits:1})));}
 assert(!html.includes('正在读取模型成绩'));
 assert(bootstrap.manifest.parts.every(p=>manifest.parts.some(q=>q.path===p.path&&q.bytes===p.bytes)));
 assert.equal(bootstrap.manifest.workspace_sha256,manifest.workspace_sha256);
 assert(Buffer.byteLength(JSON.stringify(bootstrap))<5000);
 for(const item of bootstrap.snapshot.home_summary.featured){assert(manifest.details[JSON.stringify([item.paper_id,item.benchmark_id])]);}
});

test('home initialization makes no network calls, and a source detail needs no bulk archive',async()=>{
 const html=fs.readFileSync(site+'index.html','utf8'),bootstrap=html.match(/<script id="snapshot-bootstrap" type="application\/json">([\s\S]*?)<\/script>/)[1];
 const s=setup('/papermeta-analysis/');s.seen.length=0;
 s.context.document.getElementById=id=>id==='snapshot-bootstrap'?{textContent:bootstrap}:null;
 vm.runInContext(source,s.context);
 assert.equal(s.seen.length,0);
 const code=fs.readFileSync(site+'radar.js','utf8');
 const block=code.slice(code.indexOf('  let refreshInFlight='),code.indexOf("  for(const btn of document.querySelectorAll('[data-view]'))"));
 const node={};let renders=0;
 Object.assign(s.context,{state:{snapshot:null,loading:false,view:'home'},requestedModel:null,lastRefreshAt:0,$:()=>node,setLoadingUI(){},date:x=>x,validate:x=>x,render(){renders++;},resumeInteractive(){},fetchSnapshotJSON(){throw Error('Home fetched the full archive');}});
 vm.runInContext(block,s.context);
 await s.context.refresh();assert.equal(renders,1);assert.equal(s.seen.length,0);assert.equal(s.context.state.snapshot.snapshot_id,manifest.snapshot_id);
 const pair=JSON.parse(Object.keys(manifest.details)[0]),q=new URLSearchParams({paper_id:pair[0],benchmark_id:pair[1]});
 const detail=await (await s.context.window.fetch(s.home+'api/benchmark?'+q)).json();
 assert.equal(detail.benchmark.benchmark_id,pair[1]);assert.equal(s.seen.length,1);assert(s.seen[0][0].includes('/details/'));
});

test('worker decodes all real observations and preserves every published score',async()=>{
 const s=setup('/papermeta-analysis/'),messages=[];
 s.context.self={postMessage:message=>messages.push(message)};
 s.context.fetch=s.context.window.fetch;
 s.context.importScripts=file=>vm.runInContext(fs.readFileSync(site+file,'utf8'),s.context);
 vm.runInContext(fs.readFileSync(site+'snapshot-worker.js','utf8'),s.context);
 await s.context.self.onmessage({data:{manifest:JSON.parse(fs.readFileSync(site+'snapshot/current.json')),base:s.home}});
 assert(!messages.some(m=>m.type==='error'),JSON.stringify(messages.filter(m=>m.type==='error')));
 const data=messages.find(m=>m.type==='ready').snapshot;
 assert.equal(data.observations.length,report.observations);
 const models=data.index.models.filter(m=>!m.model_setting&&m.publication_eligible);
 assert.equal(models.length,report.published_default_models);
 for(const m of models)assert.equal(m.score,report.published_default_model_scores[m.model_canonical]);
 assert.equal(s.seen.filter(([p])=>p.endsWith('.bin')).length,manifest.parts.length);
 assert(messages.filter(m=>m.type==='progress').length>=4);
});
test('project detail document resolves scripts and navigation within the project',()=>{
 const html=fs.readFileSync(site+'benchmark/index.html','utf8');assert(html.includes('<base href="../">'));assert(html.includes("document.querySelector('script[src$=\"snapshot-adapter.js\"]')"));
 const base=new URL('../','https://viewer.test/papermeta-analysis/benchmark/');
 for(const match of html.matchAll(/<script\b[^>]*src="([^"]+)"/g)){const u=new URL(match[1],base);assert(u.pathname.startsWith('/papermeta-analysis/'));assert(fs.existsSync(site+u.pathname.slice('/papermeta-analysis/'.length)));}
 assert(fs.readFileSync(site+'radar.js','utf8').includes("new URL('benchmark/?'"));
 assert(!fs.existsSync(site+'admin'));assert(fs.existsSync(site+'.nojekyll'));
});
