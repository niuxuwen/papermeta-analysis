const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const V=require('./site/radar-viz.js');
const bench=(paper_id,extra={})=>({paper_id,benchmark_id:'b',benchmark_name:paper_id,eligibility:'ELIGIBLE',...extra});
const row=(paper_id,value_numeric=0)=>({paper_id,benchmark_id:'b',value_numeric});
test('public projection hides empty verified benchmarks, retains real zero scores and preserves admin data',()=>{
  const empty=bench('NTBench',{progress:{observations:0,paper_status:'RETRY_EXHAUSTED'}}),scored=bench('scored');
  const snapshot={benchmarks:[empty,scored],observations:[row('scored')],index:{models:[{score:5}],groups:[]}};
  const before=JSON.stringify(snapshot),view=V.visitorSnapshot(snapshot);
  assert.deepEqual(view.benchmarks.map(x=>x.paper_id),['scored']);assert.equal(view.observations[0].value_numeric,0);
  assert.equal(JSON.stringify(snapshot),before);assert.strictEqual(view.index.models,snapshot.index.models);
  assert.strictEqual(V.visitorSnapshot(view),view);
});
test('merged entries need a scored allowed member; excluded aliases cannot revive an empty entry',()=>{
  const blocked=bench('blocked',{status:'EXCLUDED'}),empty=bench('empty'),member=bench('member');
  const merged=bench('merged',{catalog_sources:[empty,blocked,member]});
  const base={benchmarks:[merged,blocked],observations:[row('blocked')],index:{}};
  assert.equal(V.visitorSnapshot(base).benchmarks.length,0);
  const view=V.visitorSnapshot({...base,observations:[...base.observations,row('member')]});
  assert.equal(view.benchmarks.length,1);assert.deepEqual(view.observations.map(x=>x.paper_id),['member']);
  assert(!V.directorySources(view.benchmarks[0]).some(x=>x.paper_id==='blocked'));
});
test('light catalog uses established counts while full evidence overrides stale summaries',()=>{
  const scored=bench('scored',{catalog_display_stats:{observations:3}}),empty=bench('empty',{progress:{observations:0}});
  const light={sources_loaded:false,benchmarks:[scored,empty],observations:[]};
  assert.deepEqual(V.visitorSnapshot(light).benchmarks.map(x=>x.paper_id),['scored']);
  assert.equal(V.visitorSnapshot({...light,sources_loaded:true}).benchmarks.length,0);
  assert.equal(V.publicBenchmarkVisible(scored,[]),false);assert.equal(V.publicBenchmarkVisible(scored),true);
});
test('bookmarked empty detail is hidden for visitors and still inspectable by management',()=>{
  const path=fs.existsSync('site/benchmark/index.html')?'site/benchmark/index.html':'site/benchmark.html';
  const html=fs.readFileSync(path,'utf8'),start=html.indexOf('function render(d){'),end=html.indexOf('\n',start);
  const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);};
  const c={URLSearchParams,window:{RadarViz:V},location:{search:''},document:{body:{dataset:{},classList:{toggle(){}}},getElementById:get},renderNameAudit(){throw Error('management_render_reached');}};
  vm.createContext(c);vm.runInContext(html.slice(start,end),c);
  const data={benchmark:bench('NTBench',{progress:{observations:8}}),observations:[]};
  c.render(data);assert.equal(get('title').textContent,'该评测暂未公开展示');
  c.location.search='?edition=admin';assert.throws(()=>c.render(data),/management_render_reached/);
});
