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
      visitor_catalog_filtered:true,detail_loaded:true,status:{jobs:[]},
      observations:sources,index:{method:publicData.index.method,models:models.get(name)||[],groups:groups.get(name)||[]},
      benchmarks:publicData.benchmarks.filter(b=>ids.has(JSON.stringify([b.paper_id,b.benchmark_id]))).map(b=>pick(b,['paper_id','benchmark_id','benchmark_name','paper_title','name_audit','eligibility']))};
    const raw=zlib.gzipSync(JSON.stringify(detail),{level:9}),sha=crypto.createHash('sha256').update(raw).digest('hex'),file=modelRoot+sha.slice(0,24)+'.json.gz';
    fs.writeFileSync(path.join(site,file),raw);dossiers[name]={path:file,bytes:raw.length,sha256:sha};
  }
  // Model identity metadata is shared verbatim; repeating it in every dossier
  // makes large live generations slow to compress and unnecessarily large.
  const indexBytes=zlib.gzipSync(JSON.stringify({snapshot_id:snapshot.snapshot_id,models:dossiers,model_registry:publicData.model_registry}),{level:9}),indexHash=crypto.createHash('sha256').update(indexBytes).digest('hex'),indexPath=modelRoot+'index-'+indexHash.slice(0,16)+'.json.gz';
  fs.writeFileSync(path.join(site,indexPath),indexBytes);manifest.model_details={path:indexPath,bytes:indexBytes.length,sha256:indexHash,snapshot_id:snapshot.snapshot_id};
  const charts={};
  for(const setting of V.settings(publicData)){
    const chart=V.visitorChartData(V.modelData(publicData,setting));
    charts[setting]={...chart,cells:chart.cells.map(c=>({...c,proof:(c.proof||[]).map(p=>pick(p,['paper','benchmark','group','table','metric','row','raw']))}))};
  }
  const modelKeys=['model_canonical','model_setting','score','publication_score','publication_eligible','publication_status','status','score_panel_id','provisional','blocked_group_ids','n_benchmarks','n_groups','coverage_pct','score_unit','publication_min_source_papers','available_benchmarks'];
  const identity=b=>JSON.stringify([b.paper_id,b.benchmark_id]),byBenchmark=new Map(),annotations=new Map();
  for(const row of publicData.observations){const id=identity(row);if(!byBenchmark.has(id))byBenchmark.set(id,[]);byBenchmark.get(id).push(row);}
  for(const row of publicData.capability_annotations?.items||[]){const id=identity(row);if(!annotations.has(id))annotations.set(id,[]);annotations.get(id).push(row);}
  const catalog=publicData.benchmarks.map(b=>{
    const item=pick(b,['paper_id','benchmark_id','benchmark_name','paper_title','release_date','paper_first_published','eligibility','arxiv_id','source_benchmark_name','benchmark_aliases','catalog_identity','catalog_aliases','directory_identity','directory_aliases','directory_grouping_basis','name_audit']);
    for(const key of ['catalog_sources','directory_sources'])if(b[key])item[key]=b[key].map(ref=>pick(ref,['paper_id','benchmark_id','paper_title']));
    item.progress=pick(b.progress||{},['paper_status','observations','models','tables']);
    item.catalog_display_tags={};
    for(const layer of ['domains','tasks','capabilities']){
      const labels=b.enrichment?.labels,values=labels?.supported?.[layer]||(labels?.status==='SUPPORTED'?labels[layer]:[]);
      const ids=new Set((Array.isArray(values)?values:[]).map(x=>typeof x==='string'?x:x.id).filter(Boolean));
      for(const id of b.catalog_labels?.[layer]||[])ids.add(id);
      for(const a of annotations.get(identity(b))||[])if(a.status==='SUPPORTED')for(const id of a[layer]||[])ids.add(id);
      item.catalog_display_tags[layer]=[...ids];
    }
    const rows=V.directorySources(b).flatMap(ref=>byBenchmark.get(identity(ref))||[]);
    item.catalog_display_stats={observations:rows.length,models:new Set(rows.map(o=>o.model_canonical).filter(Boolean)).size,tables:new Set(rows.filter(o=>o.table_id!=null).map(o=>JSON.stringify([o.paper_id,o.table_id]))).size};
    return item;
  });
  const browse={snapshot_id:snapshot.snapshot_id,generated_at:snapshot.generated_at,window:snapshot.window,status:{...snapshot.status,jobs:[]},
    detail_loaded:true,sources_loaded:false,catalog_loaded:true,visitor_catalog_filtered:true,visitor_catalog_count:publicData.visitor_catalog_count,
    benchmarks:catalog,observations:[],
    model_registry:publicData.model_registry,index:{method:publicData.index.method,models:publicData.index.models.map(m=>pick(m,modelKeys)),groups:publicData.index.groups.map(g=>pick(g,['group_id','paper_id','benchmark_id','model_setting','relative_status','blocked_reasons','extraction_in_progress']))},
    capability_annotations:{...pick(publicData.capability_annotations||{},['total_groups','unannotated_groups']),items:(publicData.capability_annotations?.items||[]).map(a=>pick(a,['group_id','paper_id','benchmark_id','status','capabilities','domains','tasks']))},capability_atlas:publicData.capability_atlas,ranking_charts:charts};
  const bytes=zlib.gzipSync(JSON.stringify(browse),{level:9}),sha=crypto.createHash('sha256').update(bytes).digest('hex');
  const relative=`snapshot/${manifest.snapshot_id}/ranking-${sha.slice(0,16)}.json.gz`;
  fs.writeFileSync(path.join(site,relative),bytes);
  manifest.ranking={path:relative,bytes:bytes.length,sha256:sha,snapshot_id:manifest.snapshot_id};
  // Comparison controls need original groups and annotations, not every model's
  // scoring audit and every observation's repeated paper context.
  const comparisons={snapshot_id:snapshot.snapshot_id,groups:publicData.index.groups,annotations:publicData.capability_annotations,
    labels:publicData.benchmarks.map(b=>({paper_id:b.paper_id,benchmark_id:b.benchmark_id,labels:pick(b.enrichment?.labels||{},['status','supported','capabilities','domains','tasks'])}))};
  const comparisonBytes=zlib.gzipSync(JSON.stringify(comparisons),{level:9}),comparisonRoot=`snapshot/${manifest.snapshot_id}/comparisons/`,parts=[];
  fs.mkdirSync(path.join(site,comparisonRoot),{recursive:true});
  for(let offset=0;offset<comparisonBytes.length;offset+=262144){
    const raw=comparisonBytes.subarray(offset,offset+262144),hash=crypto.createHash('sha256').update(raw).digest('hex'),file=comparisonRoot+hash.slice(0,24)+'.bin';
    fs.writeFileSync(path.join(site,file),raw);parts.push({path:file,bytes:raw.length,sha256:hash});
  }
  const comparisonIndex=Buffer.from(JSON.stringify({snapshot_id:snapshot.snapshot_id,parts,bytes:comparisonBytes.length,sha256:crypto.createHash('sha256').update(comparisonBytes).digest('hex')})),comparisonHash=crypto.createHash('sha256').update(comparisonIndex).digest('hex'),comparisonPath=comparisonRoot+'index-'+comparisonHash.slice(0,16)+'.json';
  fs.writeFileSync(path.join(site,comparisonPath),comparisonIndex);manifest.comparisons={path:comparisonPath,bytes:comparisonIndex.length,sha256:comparisonHash,snapshot_id:snapshot.snapshot_id};
  fs.writeFileSync(path.join(site,'snapshot/manifest.json'),JSON.stringify(manifest));
  console.log(JSON.stringify({ranking_bytes:bytes.length,comparison_bytes:comparisonBytes.length,comparison_parts:parts.length,archive_bytes:manifest.parts.reduce((n,p)=>n+p.bytes,0),settings:Object.keys(charts).length,models:browse.index.models.length}));
  return browse;
};
