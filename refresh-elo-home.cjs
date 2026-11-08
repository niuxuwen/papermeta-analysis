const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const V = require('./site/radar-viz.js');
const site = path.join(__dirname, 'site');
const read = name => fs.readFileSync(path.join(site, name));
const manifest = JSON.parse(read('snapshot/current.json'));
const board = JSON.parse(read('snapshot-elo-data.js').toString().slice('window.snapshotElo = '.length,-1));
if (board.snapshot_id !== manifest.snapshot_id || board.task_inputs_sha256 !== manifest.task_inputs.sha256) {
  throw Error('Elo inputs do not match the current snapshot');
}
const ranking = JSON.parse(zlib.gunzipSync(read(manifest.ranking.path)));
V.setModelRegistry(ranking.model_registry);
const top = board.models.filter(r=>!r.setting).slice(0,6);
const escape = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const buttons = top.map((r,i)=>{
  const name=escape(r.model), vendor=V.modelInfo(r.model).vendor;
  return `<button type="button" class="visitor-model-row" data-home-model="${name}"><span class="visitor-rank">${String(i+1).padStart(2,'0')}</span><span class="visitor-model-swatch" style="background:${V.vendorColor(vendor)}"></span><span class="visitor-model-name"><strong>${name}</strong><small>${escape(vendor)} · ${r.benchmarks} 项评测</small></span><strong class="visitor-model-score">${r.basket_score_0_100.toFixed(1)}</strong></button>`;
}).join('');
let html=read('index.html').toString();
html=html.replace(/<script src="\.\/snapshot-elo-data\.js[^"]*"><\/script>/g,'')
  .replace('<script src="./snapshot-adapter.js','<script src="./snapshot-elo-data.js"></script><script src="./snapshot-adapter.js')
  .replace(/(<div id="visitor-top-models"[^>]*>)[\s\S]*?(<\/div><\/section>)/,(_,a,b)=>a+buttons+b)
  .replace('<h2>模型综合评分</h2>','<h2>综合评分</h2>')
  .replace(/(<script id="snapshot-bootstrap"[^>]*>)([\s\S]*?)(<\/script>)/,(_,a,data,b)=>{
    const boot=JSON.parse(data);
    boot.snapshot.home_summary.models=top.map(r=>({name:r.model,score:r.basket_score_0_100,nBenchmarks:r.benchmarks,vendor:V.modelInfo(r.model).vendor}));
    return a+JSON.stringify(boot).replace(/</g,'\\u003c')+b;
  })
  .replace(/src="\.\/(snapshot-elo-data|radar-viz|radar)\.js(?:\?v=[a-f0-9]+)?"/g,(_,n)=>
    `src="./${n}.js?v=${crypto.createHash('sha256').update(read(n+'.js')).digest('hex').slice(0,12)}"`);
if(!html.includes('src="./snapshot-elo-data.js?') || !html.includes(buttons))throw Error('Home template mismatch');
fs.writeFileSync(path.join(site,'index.html.tmp'),html);
fs.renameSync(path.join(site,'index.html.tmp'),path.join(site,'index.html'));
