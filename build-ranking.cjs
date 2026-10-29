/* Exact display projection: scoring and original source archives stay unchanged. */
module.exports=function(snapshot,publicData,V,manifest,site){
  const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
  const pick=(row,keys)=>Object.fromEntries(keys.filter(k=>k in row).map(k=>[k,row[k]]));
  const charts={};
  for(const setting of V.settings(publicData)){
    const chart=V.visitorChartData(V.modelData(publicData,setting));
    charts[setting]={...chart,cells:chart.cells.map(c=>({...c,proof:(c.proof||[]).map(p=>pick(p,['paper','benchmark','group','table','metric','row','raw']))}))};
  }
  const modelKeys=['model_canonical','model_setting','score','publication_score','publication_eligible','publication_status','status','score_panel_id','provisional','blocked_group_ids','n_benchmarks','n_groups','coverage_pct','score_unit','publication_min_source_papers','available_benchmarks'];
  const browse={snapshot_id:snapshot.snapshot_id,generated_at:snapshot.generated_at,window:snapshot.window,status:{...snapshot.status,jobs:[]},
    detail_loaded:true,sources_loaded:false,visitor_catalog_filtered:true,visitor_catalog_count:publicData.visitor_catalog_count,
    benchmarks:publicData.benchmarks.map(b=>pick(b,['paper_id','benchmark_id','benchmark_name','paper_title','release_date','eligibility'])),observations:[],
    model_registry:publicData.model_registry,index:{method:publicData.index.method,models:publicData.index.models.map(m=>pick(m,modelKeys)),groups:publicData.index.groups.map(g=>pick(g,['group_id','paper_id','benchmark_id','model_setting','relative_status','blocked_reasons','extraction_in_progress']))},
    capability_annotations:{items:[]},ranking_charts:charts};
  const bytes=zlib.gzipSync(JSON.stringify(browse),{level:9}),sha=crypto.createHash('sha256').update(bytes).digest('hex');
  const relative=`snapshot/${manifest.snapshot_id}/ranking-${sha.slice(0,16)}.json.gz`;
  fs.writeFileSync(path.join(site,relative),bytes);
  manifest.ranking={path:relative,bytes:bytes.length,sha256:sha,snapshot_id:manifest.snapshot_id};
  fs.writeFileSync(path.join(site,'snapshot/manifest.json'),JSON.stringify(manifest));
  console.log(JSON.stringify({ranking_bytes:bytes.length,archive_bytes:manifest.parts.reduce((n,p)=>n+p.bytes,0),settings:Object.keys(charts).length,models:browse.index.models.length}));
  return browse;
};
