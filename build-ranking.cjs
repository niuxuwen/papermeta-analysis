/* Exact display projection: scoring and original source archives stay unchanged. */
module.exports=function(snapshot,publicData,V,manifest,site){
  const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
  const pick=(row,keys)=>Object.fromEntries(keys.filter(k=>k in row).map(k=>[k,row[k]]));
  const modelRoot=`snapshot/${manifest.snapshot_id}/models/`;fs.mkdirSync(path.join(site,modelRoot),{recursive:true});
  const observations=new Map(),models=new Map(),groups=new Map(),dossiers={};
  for(const row of publicData.observations){if(!observations.has(row.model_canonical))observations.set(row.model_canonical,[]);observations.get(row.model_canonical).push(row);}
  for(const row of publicData.index.models){if(!models.has(row.model_canonical))models.set(row.model_canonical,[]);models.get(row.model_canonical).push(row);}
  for(const group of publicData.index.groups)for(const score of group.scores||[]){
    if(!groups.has(score.model_canonical))groups.set(score.model_canonical,[]);
    groups.get(score.model_canonical).push({...pick(group,['group_id','paper_id','benchmark_id','model_setting','blocked_reasons','extraction_in_progress','benchmark_identity']),scores:[score]});
  }
  for(const name of new Set([...observations.keys(),...models.keys()])){
    const sources=observations.get(name)||[],ids=new Set(sources.map(r=>JSON.stringify([r.paper_id,r.benchmark_id])));
    const detail={snapshot_id:snapshot.snapshot_id,generated_at:snapshot.generated_at,model_name:name,window:snapshot.window,
      visitor_catalog_filtered:true,detail_loaded:true,status:{jobs:[]},model_registry:publicData.model_registry,
      observations:sources,index:{method:publicData.index.method,models:models.get(name)||[],groups:groups.get(name)||[]},
      benchmarks:publicData.benchmarks.filter(b=>ids.has(JSON.stringify([b.paper_id,b.benchmark_id]))).map(b=>pick(b,['paper_id','benchmark_id','benchmark_name','paper_title','name_audit','eligibility']))};
    const raw=zlib.gzipSync(JSON.stringify(detail),{level:9}),sha=crypto.createHash('sha256').update(raw).digest('hex'),file=modelRoot+sha.slice(0,24)+'.json.gz';
    fs.writeFileSync(path.join(site,file),raw);dossiers[name]={path:file,bytes:raw.length,sha256:sha};
  }
  const indexBytes=zlib.gzipSync(JSON.stringify({snapshot_id:snapshot.snapshot_id,models:dossiers}),{level:9}),indexHash=crypto.createHash('sha256').update(indexBytes).digest('hex'),indexPath=modelRoot+'index-'+indexHash.slice(0,16)+'.json.gz';
  fs.writeFileSync(path.join(site,indexPath),indexBytes);manifest.model_details={path:indexPath,bytes:indexBytes.length,sha256:indexHash,snapshot_id:snapshot.snapshot_id};
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
