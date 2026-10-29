const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const V=require('./site/radar-viz.js'),real=require('./validation/task-broad-real-v121.json');
for(const [name,report] of Object.entries(real))test('all-scenario view retains every real '+name+' result without combining condition scores',()=>{
  const before=JSON.stringify(report),view=V.taskOverview(report);
  assert.equal(view.benchmarks,report.benchmark_matches.length);
  assert.equal(view.models,new Set(report.models.filter(m=>m.publication_eligible).map(m=>m.model_canonical)).size);
  assert.equal(view.groups,new Set(report.panel.map(g=>g.group_id)).size);
  assert.equal(view.scenarios.flatMap(s=>s.panels).length,new Set(report.models.map(m=>m.panel_id)).size);
  assert.equal(view.panels.flatMap(p=>p.models).length,report.models.length);
  for(const panel of view.panels)for(const m of panel.models)assert.equal(m.publication_score,report.models.find(r=>r===m).publication_score);
  assert.equal(JSON.stringify(report),before);
});
test('real coding task exposes all 10 benchmarks and 54 models rather than the first small group',()=>{
  const r=real['code-development'],v=V.taskOverview(r);assert.equal(v.benchmarks,10);assert.equal(v.models,54);
  const web=v.scenarios.find(s=>s.id==='web_functionality');assert.equal(web.panels.length,4);
  assert.equal(new Set(web.panels.map(p=>p.id)).size,4);assert.equal(v.panels.length,28);
});
test('empty task evidence does not invent scenarios or scores',()=>{
  const v=V.taskOverview({models:[],panel:[]});assert.equal(v.models,0);assert.equal(v.benchmarks,0);assert.equal(v.scenarios.length,0);
});
test('default candidate selection includes every task-related model and follows task edits',()=>{
  const s=fs.readFileSync(__dirname+'/site/radar.js','utf8'),start=s.indexOf('    const suggested=rows.filter(r=>r.nTaskBenchmarks);');
  const c={known:new Set(['A','B','C','D']),rows:[{name:'A',nTaskBenchmarks:1},{name:'B',nTaskBenchmarks:2},{name:'C',nTaskBenchmarks:0}],taskState:{autoCandidates:true,refsInitialized:false}};
  const run=()=>vm.runInContext('{'+s.slice(start,s.indexOf('    const context=',start))+'}',c);
  vm.createContext(c);run();assert.deepEqual([...c.taskState.refs],['A','B']);
  c.rows.push({name:'D',nTaskBenchmarks:1});run();assert(c.taskState.refs.has('D'));
  c.taskState.autoCandidates=false;c.taskState.refs=new Set(['A']);run();assert.deepEqual([...c.taskState.refs],['A']);
});
