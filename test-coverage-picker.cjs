const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),zlib=require('node:zlib');
const V=require('./site/radar-viz.js');
const manifest=JSON.parse(fs.readFileSync(__dirname+'/site/snapshot/current.json'));
const ranking=JSON.parse(zlib.gunzipSync(fs.readFileSync(__dirname+'/site/'+manifest.ranking.path)));
V.setModelRegistry(ranking.model_registry);
test('coverage picker retains every positive-coverage real model and excludes zero-coverage entries',()=>{
 let rows=0,zero=0;
 for(const setting of V.settings(ranking)){
  const data=V.coverageData(V.modelData(ranking,setting));
  const expected=data.rows.filter(r=>r.nBenchmarks>0).map(r=>r.name).sort();
  assert.deepEqual(V.modelPickerRows(data).map(r=>r.name).sort(),expected);
  assert.deepEqual([...V.pickerSelection(data,{replace:true})].sort(),expected);
  rows+=expected.length;zero+=data.rows.filter(r=>r.nBenchmarks===0).length;
 }
 assert(rows>0);assert(zero>0);
});
test('a real raw score of zero remains selectable in benchmark charts',()=>{
 const data={kind:'benchmark',axes:[{id:'raw'}],rows:[{name:'zero'}],cells:[{name:'zero',axis:'raw',value:0}]};
 assert.equal(V.modelPickerRows(data).length,1);
});
