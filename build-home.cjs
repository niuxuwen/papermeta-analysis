/* Build the public landing page from the verified, unchanged source snapshot. */
const fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib'),crypto=require('node:crypto');
const path=require('node:path'),site=path.join(__dirname,'site');
const read=name=>fs.readFileSync(path.join(site,name),'utf8');
const manifest=JSON.parse(read('snapshot/manifest.json'));
const packed=Buffer.concat(manifest.parts.map(p=>{const bytes=fs.readFileSync(path.join(site,p.path));if(bytes.length!==p.bytes)throw Error('PART_LENGTH');return bytes;}));
if(crypto.createHash('sha256').update(packed).digest('hex')!==manifest.workspace_sha256)throw Error('SNAPSHOT_HASH');
const radar=read('radar.js');
const decoder=radar.slice(radar.indexOf('  function decodeSnapshot('),radar.indexOf('  async function fetchSnapshotJSON('));
const context={console,Intl,URL};context.window=context;vm.createContext(context);
vm.runInContext(decoder+'\n'+read('radar-viz.js'),context);
const snapshot=context.decodeSnapshot(JSON.parse(zlib.gunzipSync(packed)));
const V=context.RadarViz,publicData=V.visitorSnapshot(snapshot);V.setModelRegistry(publicData.model_registry);
const rows=V.modelData(publicData,'').rows.filter(r=>Number.isFinite(r.score)).sort((a,b)=>b.score-a.score||a.name.localeCompare(b.name));
const names=new Set(),top=rows.filter(r=>!names.has(r.name)&&names.add(r.name)).slice(0,6);
const stats=new Map();
for(const row of publicData.observations){const key=JSON.stringify([row.paper_id,row.benchmark_id]);if(!stats.has(key))stats.set(key,{count:0,models:new Set()});const stat=stats.get(key);stat.count++;if(row.model_canonical)stat.models.add(row.model_canonical);}
const seen=new Set(),featured=publicData.benchmarks.filter(b=>b.eligibility==='ELIGIBLE'&&stats.has(JSON.stringify([b.paper_id,b.benchmark_id])))
  .sort((a,b)=>(Date.parse(b.paper_first_published)||0)-(Date.parse(a.paper_first_published)||0)||a.benchmark_name.localeCompare(b.benchmark_name))
  .filter(b=>{const key=V.directoryKey(b);return !seen.has(key)&&seen.add(key);}).slice(0,4);
const {details,...lean}=manifest;
lean.details_root=`snapshot/${manifest.snapshot_id}/details/`;
fs.writeFileSync(path.join(site,'snapshot/current.json'),JSON.stringify(lean));
const summary={snapshot_id:snapshot.snapshot_id,generated_at:snapshot.generated_at,window:snapshot.window,
  status:{counts:snapshot.status.counts,evidence_generated_at:snapshot.status.evidence_generated_at,jobs:[]},
  benchmarks:[],observations:[],index:{models:[],groups:[]},detail_loaded:false,
  capability_annotations:{items:[],total_groups:0,unannotated_groups:0},
  home_summary:{models:top.map(r=>({name:r.name,score:r.score,nBenchmarks:r.nBenchmarks,vendor:V.modelInfo(r.name).vendor})),
    featured:featured.map(b=>({paper_id:b.paper_id,benchmark_id:b.benchmark_id,name:b.benchmark_name}))}};
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modelHTML=top.map((r,i)=>{
 const info=V.modelInfo(r.name),score=r.score.toLocaleString('zh-CN',{maximumFractionDigits:1});
 return `<button type="button" class="visitor-model-row" data-home-model="${escape(r.name)}" aria-label="查看 ${escape(r.name)} 的模型详情，综合分 ${score}"><span class="visitor-rank">${String(i+1).padStart(2,'0')}</span><span class="visitor-model-swatch" style="background:${V.vendorColor(info.vendor)}"></span><span class="visitor-model-name"><strong>${escape(r.name)}</strong><small>${escape(info.vendor)} · ${r.nBenchmarks??'—'} 项评测</small></span><strong class="visitor-model-score">${score}</strong></button>`;
}).join('');
const featuredHTML=featured.map(b=>{
 const stat=stats.get(JSON.stringify([b.paper_id,b.benchmark_id]));
 const href='benchmark/?'+new URLSearchParams({paper_id:b.paper_id,benchmark_id:b.benchmark_id});
 return `<a class="visitor-benchmark-row" href="${escape(href)}" aria-label="查看 ${escape(b.benchmark_name)} 的评测详情"><span class="visitor-benchmark-copy"><strong>${escape(b.benchmark_name)}</strong><span class="visitor-benchmark-description">${escape(b.paper_title)}</span><small>${stat.models.size} 个模型 · ${stat.count.toLocaleString('zh-CN')} 条来源成绩</small></span></a>`;
}).join('');
let html=read('index.html');
html=html.replace(/<script id="snapshot-bootstrap"[\s\S]*?<\/script>/,'');
html=html.replace('<meta charset="utf-8">','<meta charset="utf-8"><script id="snapshot-bootstrap" type="application/json">'+JSON.stringify({manifest:lean,snapshot:summary}).replace(/</g,'\\u003c')+'</script>');
html=html.replace('<script src="./snapshot-adapter.js"></script>','<script src="./snapshot-adapter.js" defer></script>');
html=html.replace(/(<div id="visitor-top-models"[^>]*>)[\s\S]*?(<\/div><p class="visitor-ranking-note">)/,(_,open,close)=>open+modelHTML+close);
html=html.replace(/(<div id="visitor-featured"[^>]*>)[\s\S]*?(<\/div><\/section><\/div>)/,(_,open,close)=>open+featuredHTML+close);
html=html.replace(/(src|href)="\.\/([^"?]+\.(?:js|css))(?:\?v=[a-f0-9]+)?"/g,(_,attr,name)=>`${attr}="./${name}?v=${crypto.createHash('sha256').update(fs.readFileSync(path.join(site,name))).digest('hex').slice(0,12)}"`);
fs.writeFileSync(path.join(site,'index.html'),html);
fs.writeFileSync(path.join(site,'snapshot-codec.js'),'/* Generated by build-home.cjs from the application decoder. */\n'+decoder);
const report={snapshot_id:manifest.snapshot_id,generated_at:manifest.generated_at,source_sha256:manifest.source_sha256,
 initial_snapshot_download_bytes:0,previous_required_snapshot_bytes:packed.length+fs.statSync(path.join(site,'snapshot/manifest.json')).size+fs.statSync(path.join(site,manifest.overview)).size,
 embedded_bootstrap_bytes:Buffer.byteLength(JSON.stringify({manifest:lean,snapshot:summary})),compact_manifest_bytes:Buffer.byteLength(JSON.stringify(lean)),
 models:summary.home_summary.models,featured:summary.home_summary.featured,observations:snapshot.observations.length};
fs.writeFileSync(path.join(__dirname,'performance-validation.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({initial_snapshot_download_bytes:0,previous_required_snapshot_bytes:report.previous_required_snapshot_bytes,embedded_bootstrap_bytes:report.embedded_bootstrap_bytes,compact_manifest_bytes:report.compact_manifest_bytes,models:top.length,featured:featured.length}));
