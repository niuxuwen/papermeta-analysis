'use strict';
const key=row=>JSON.stringify([row.paper_id,row.benchmark_id]);
module.exports=function project(snapshot,registry){
  if(!registry)return snapshot;
  if(registry.snapshot_id!==snapshot.snapshot_id)throw Error('BENCHMARK_ENTITY_SNAPSHOT_MISMATCH');
  const mappings=new Map(registry.mappings.map(m=>[key(m),m]));
  if(mappings.size!==registry.mappings.length||mappings.size!==snapshot.benchmarks.length)throw Error('BENCHMARK_ENTITY_MAPPING_INCOMPLETE');
  const originals=new Map(snapshot.benchmarks.map(b=>[key(b),b])),variantRefs=new Map();
  const pick=b=>Object.fromEntries(['paper_id','benchmark_id','benchmark_name','paper_title','arxiv_id','source_url','release_date','eligibility','status','history_status','name_audit'].filter(k=>k in b).map(k=>[k,b[k]]));
  for(const variant of registry.variants){
    const refs=variant.sources.map(ref=>{const b=originals.get(key(ref));if(!b)throw Error('BENCHMARK_ENTITY_UNKNOWN_SOURCE');return pick(b);});
    variantRefs.set(variant.variant_id,refs);
  }
  const benchmarks=snapshot.benchmarks.map(b=>{
    const m=mappings.get(key(b));if(!m)throw Error('BENCHMARK_ENTITY_SOURCE_MISSING');
    const extra={benchmark_entity_id:m.entity_id,benchmark_variant_id:m.variant_id,
      benchmark_entity_name:m.canonical_name,benchmark_entity_status:m.status,benchmark_entity_match_basis:m.match_basis};
    if(m.status!=='RESOLVED')return {...b,...extra};
    const refs=variantRefs.get(m.variant_id);if(!refs)throw Error('BENCHMARK_ENTITY_VARIANT_MISSING');
    return {...b,...extra,directory_identity:m.variant_id,directory_grouping_basis:'CROSS_PAPER_DATASET_VARIANT',
      directory_sources:refs,directory_aliases:[...new Set(refs.map(r=>r.benchmark_name))]};
  });
  return {...snapshot,benchmarks,benchmark_entity_statistics:registry.statistics,benchmark_entity_version:registry.version};
};
