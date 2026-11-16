import test from 'node:test';
import assert from 'node:assert/strict';
import {judge,normalizeQuery,sha256} from './judge-client.mjs';
import {dateLabel,renderReleaseDate} from './benchmark-date-view.mjs';

const meta={snapshot_id:'s1',source_sha256:'source',registry_sha256:'registry',generation:'g1',source_generated_at:'2026-11-16T01:00:00Z'};
async function fixture({homonym=false}={}) {
 const key='toolturns',id='toolturns',prefix=(await sha256(new TextEncoder().encode(key))).slice(0,2),root='https://example.org/releases/g/api/v1/';
 const row={entity_id:id,name:'ToolTurns',judgment:'NEW_IN_PERIOD',is_new_in_report_period:true,needs_research:false,benchmark_date_status:'VERIFIED_FIRST_PUBLIC',benchmark_first_public_date:'2026-11-11',source_refs:[{paper_id:'p1',benchmark_id:'b1'}]};
 const ids=homonym?[id,'another']: [id],lookup={...meta,items:{[key]:ids}},values={...meta,items:{[id]:row,another:{...row,entity_id:'another'}}};
 const manifest={...meta,format:'benchmark-release-judgment-api-v1',api_root:'./',lookup:{},judgments:{},notice:'pending is not zero'};
 const map=new Map();
 for(let i=0;i<256;i++){const p=i.toString(16).padStart(2,'0');manifest.lookup[p]={empty:true};manifest.judgments[p]={empty:true};}
 async function store(category,p,value){const raw=new TextEncoder().encode(JSON.stringify(value)),path=category+'/'+p+'.json';map.set(root+path,raw);manifest[category][p]={path,bytes:raw.length,sha256:await sha256(raw)};}
 await store('lookup',prefix,lookup);
 for(const p of new Set(await Promise.all(ids.map(async x=>(await sha256(new TextEncoder().encode(x))).slice(0,2)))))await store('judgments',p,values);
 const fetcher=async url=>new Response(map.get(String(url))||JSON.stringify(manifest),{status:map.has(String(url))||String(url).endsWith('manifest.json')?200:404});
 return {root,manifest,map,fetcher,row,prefix};
}

test('exact lookup returns a hash-verified judgment',async()=>{const f=await fixture(),r=await judge('ＴｏｏｌＴｕｒｎｓ',new URL(f.root+'manifest.json'),f.fetcher);assert.equal(r.judgment,'NEW_IN_PERIOD');assert.equal(r.matches[0].benchmark_first_public_date,'2026-11-11');});
test('unknown returns pending without making a false old judgment',async()=>{const f=await fixture(),r=await judge('unknown',new URL(f.root+'manifest.json'),f.fetcher);assert.equal(r.result_status,'NOT_FOUND');assert.equal(r.is_new_in_report_period,null);});
test('homonyms remain ambiguous',async()=>{const f=await fixture({homonym:true}),r=await judge('ToolTurns',new URL(f.root+'manifest.json'),f.fetcher);assert.equal(r.result_status,'AMBIGUOUS');assert.equal(r.is_new_in_report_period,null);assert.equal(r.matches.length,2);});
test('corruption is an error, not an existing judgment',async()=>{const f=await fixture();f.map.set(f.root+'lookup/'+f.prefix+'.json',new TextEncoder().encode('corrupt'));await assert.rejects(judge('ToolTurns',new URL(f.root+'manifest.json'),f.fetcher),/校验失败/);});
test('normalization preserves versions of distinct benchmarks',()=>{assert.equal(normalizeQuery('https://arxiv.org/abs/2611.14925v2'),'2611.14925');assert.notEqual(normalizeQuery('MMLU-Pro'),normalizeQuery('MMLU'));});
test('public-by bound is never labeled as exact first date',()=>{assert.match(dateLabel({first_public_on_or_before:'2026-11-06'}),/待核；最迟/);assert.match(dateLabel({benchmark_date_status:'NOT_A_BENCHMARK'}),/不适用/);});

function node(){return {dataset:{},textContent:'',isConnected:true,children:[],append(x){this.children.push(x);}};}
globalThis.document={createElement:()=>node()};
test('detail date uses exact source identity without modifying raw date',async()=>{const f=await fixture(),n=node(),b={paper_id:'p1',benchmark_id:'b1',release_date:'2026-11-14'};await renderReleaseDate(n,b,{snapshotId:'s1',queryFunction:async()=>({...meta,matches:[f.row]})});assert.match(n.textContent,/2026-11-11（已核实）/);assert.equal(b.release_date,'2026-11-14');assert.equal(n.children.length,1);});
test('detail refuses a newer or older mismatched score snapshot',async()=>{const f=await fixture(),n=node();await renderReleaseDate(n,{paper_id:'p1',benchmark_id:'b1'},{snapshotId:'s2',queryFunction:async()=>({...meta,matches:[f.row]})});assert.match(n.textContent,/待核/);assert.doesNotMatch(n.textContent,/已核实/);});
test('detail never borrows another paper date via a homonym',async()=>{const f=await fixture(),n=node();await renderReleaseDate(n,{paper_id:'different',benchmark_id:'b1'},{snapshotId:'s1',queryFunction:async()=>({...meta,matches:[f.row]})});assert.match(n.textContent,/尚未核实唯一身份/);});
test('date lookup failure leaves scores and source dates usable',async()=>{const n=node();await renderReleaseDate(n,{paper_id:'p1',benchmark_id:'b1'},{snapshotId:'s1',queryFunction:async()=>{throw Error('offline');}});assert.match(n.textContent,/首发：待核/);});

 test('registered paper fallback is shown without claiming verified firstness',()=>{assert.match(dateLabel({registered_date:{benchmark_date:'2026-11-13',date_is_fallback:true}}),/2026-11-13（论文日期回填）/);assert.match(dateLabel({registered_date:{excluded:true,exclusion_reason:'METHOD'}}),/已排除/);});
