const assert=require('node:assert/strict');
const viz=require('../site/radar-viz.js');
const board={snapshot_id:'test',display_min_papers:5,models:[
  {model:'Visible',setting:'',papers:5,elo_scale:1265,source_names:[]},
  {model:'Auxiliary',setting:'',papers:1,elo_scale:1485,source_names:[]}
]};
globalThis.snapshotElo=board;const original=JSON.stringify(board);
assert.deepEqual(viz.localElo({snapshot_id:'test'}).models.map(r=>r.model),['Visible']);
assert.equal(viz.modelData({snapshot_id:'test'},'').rows[0].score,1265);
assert.equal(JSON.stringify(board),original);
board.display_min_papers=1;
assert.equal(viz.localElo({snapshot_id:'test'}).models.length,2);
assert.equal(viz.localElo({snapshot_id:'test'}).models[0].elo_scale,1265);
board.display_min_papers=7;
assert.equal(viz.localElo({snapshot_id:'test'}).models.length,0);
assert.equal(board.models.length,2);
assert.equal(board.models[0].elo_scale,1265);
assert.equal(viz.localElo({snapshot_id:'other'}),null);
board.display_min_papers=1;
for(const r of board.models)r.elo_scale=null;
assert.equal(viz.localElo({snapshot_id:'test'}).models.length,0);
console.log('PASS: coverage filters only display; original fitted scores and rows unchanged');
