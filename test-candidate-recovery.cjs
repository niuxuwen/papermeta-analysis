const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib');
const site=__dirname+'/site/',manifest=JSON.parse(fs.readFileSync(site+'snapshot/manifest.json'));
const radar=fs.readFileSync(site+'radar.js','utf8'),context={};vm.createContext(context);
vm.runInContext(radar.slice(radar.indexOf('  function decodeSnapshot('),radar.indexOf('  async function fetchSnapshotJSON(')),context);
const packed=Buffer.concat(manifest.parts.map(p=>fs.readFileSync(site+p.path)));
const data=context.decodeSnapshot(JSON.parse(zlib.gunzipSync(packed)));
const V=require('./site/radar-viz.js');V.setModelRegistry(data.model_registry);
const snapshot=V.visitorSnapshot(data);
function profile(){return {domains:[],tasks:[],capabilities:[{id:'domain_knowledge',weight:1}],constraints:{language:'any',modality:'any',knowledge_access:'any',min_context_tokens:null}};}

test('real task preview retains the browsable model inventory when hard constraints exclude all evidence',()=>{
 const p=profile(),matched=V.taskMatchPreview(snapshot,p);assert(matched.benchmarks>0);assert(matched.rows.some(r=>r.nTaskBenchmarks>0));
 p.constraints.knowledge_access='retrieval';const before=JSON.stringify(p),empty=V.taskMatchPreview(snapshot,p);
 assert.equal(empty.benchmarks,0);assert.equal(empty.emptyReason,'UNVERIFIED_PROTOCOL');assert(empty.matchingCounts.modality>0);
 assert.equal(empty.rows.length,matched.rows.length);assert(empty.rows.length>100);assert(empty.rows.every(r=>r.nTaskBenchmarks===0));
 assert.equal(JSON.stringify(p),before,'No silent constraint relaxation');
 p.constraints.knowledge_access='any';assert.strictEqual(V.taskMatchPreview(snapshot,p),matched);
});

test('domain diagnostics distinguish a real empty domain from an empty model archive',()=>{
 const p=profile();p.domains=['education'];const empty=V.taskMatchPreview(snapshot,p);
 assert(empty.rows.length>100);assert(empty.matchingCounts.capability>0);
 if(empty.benchmarks===0){assert.equal(empty.emptyReason,'DOMAIN_FILTER');assert.equal(empty.matchingCounts.domain,0);}
 else assert(empty.rows.some(r=>r.nTaskBenchmarks>0));
});

test('empty capability results remain explicit and do not become invented task scores',()=>{
 const p=profile();p.capabilities=[{id:'citation_reliability',weight:1}];const result=V.taskMatchPreview(snapshot,p);
 assert(result.rows.length>100);if(!result.benchmarks)assert.equal(result.emptyReason,'NO_CAPABILITY_EVIDENCE');
});

test('actual medical-literature profile matches seven real benchmarks and a nonempty model list',()=>{
 const p=profile();p.domains=['medicine'];p.tasks=['literature_review'];
 p.capabilities=[['cross_document_synthesis',.3],['domain_knowledge',.25],['summarization',.2],['information_extraction',.15],['long_context',.1]].map(([id,weight])=>({id,weight}));
 const preview=V.taskMatchPreview(snapshot,p);assert.equal(preview.benchmarks,7);
 assert.equal(preview.emptyReason,null);assert(preview.rows.filter(r=>r.nTaskBenchmarks>0).length>=6);
});

test('requesting task evidence during the lightweight home load actually starts the full load afterwards',async()=>{
 const source=radar.slice(radar.indexOf('  let refreshInFlight='),radar.indexOf('  async function refreshData('));
 const calls=[],pending=[],state={snapshot:null};
 const ctx={state,refreshData(options){calls.push(options);return new Promise(resolve=>pending.push(resolve));}};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const home=ctx.refresh(),task=ctx.refresh({details:true});assert.equal(calls.length,1);
 state.snapshot={detail_loaded:false};pending.shift()();await home;await Promise.resolve();
 assert.equal(calls.length,2);assert.equal(calls[1].details,true);
 state.snapshot={detail_loaded:true};pending.shift()();await task;
});
