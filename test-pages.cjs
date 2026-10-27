const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const site=__dirname+'/site/',source=fs.readFileSync(site+'snapshot-adapter.js','utf8'),report=JSON.parse(fs.readFileSync(__dirname+'/publication-validation.json','utf8'));
const manifest=JSON.parse(fs.readFileSync(site+'snapshot/manifest.json','utf8'));
function setup(prefix){
 const seen=[],home='https://viewer.test'+prefix;
 const original=async(input,options)=>{const u=new URL(String(input));assert(u.pathname.startsWith(prefix),'Request escaped the GitHub Pages project path');seen.push([u.pathname,options?.cache]);return new Response(fs.readFileSync(site+u.pathname.slice(prefix.length)));};
 const context={URL,Request,Response,Blob,DecompressionStream,TextDecoder,Uint8Array,Array,DOMException,crypto:webcrypto,console,location:{href:home},document:{currentScript:{src:home+'snapshot-adapter.js'},readyState:'loading',addEventListener(){}},window:{fetch:original}};
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
 assert.equal(s.seen.find(r=>r[0].endsWith('/snapshot/manifest.json'))[1],'no-store');
 assert.equal((await s.fetch(s.home+'api/task-profile',{method:'POST'})).status,403);
});
test('project detail document resolves scripts and navigation within the project',()=>{
 const html=fs.readFileSync(site+'benchmark/index.html','utf8');assert(html.includes('<base href="../">'));assert(html.includes("document.querySelector('script[src$=\"snapshot-adapter.js\"]')"));
 const base=new URL('../','https://viewer.test/papermeta-analysis/benchmark/');
 for(const match of html.matchAll(/<script\b[^>]*src="([^"]+)"/g)){const u=new URL(match[1],base);assert(u.pathname.startsWith('/papermeta-analysis/'));assert(fs.existsSync(site+u.pathname.slice('/papermeta-analysis/'.length)));}
 assert(fs.readFileSync(site+'radar.js','utf8').includes("new URL('benchmark/?'"));
 assert(!fs.existsSync(site+'admin'));assert(fs.existsSync(site+'.nojekyll'));
});
