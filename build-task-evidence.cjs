/* Derive a small, same-version task preview without loading source archives. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),zlib=require('node:zlib'),crypto=require('node:crypto');
const site=path.join(__dirname,'site'),manifestPath=path.join(site,'snapshot/manifest.json');
const manifest=JSON.parse(fs.readFileSync(manifestPath));
const packed=Buffer.concat(manifest.parts.map(p=>fs.readFileSync(path.join(site,p.path))));
if(crypto.createHash('sha256').update(packed).digest('hex')!==manifest.workspace_sha256)throw Error('SNAPSHOT_HASH');
const source=fs.readFileSync(path.join(site,'radar.js'),'utf8'),ctx={};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function decodeSnapshot('),source.indexOf('  async function fetchSnapshotJSON(')),ctx);
const full=ctx.decodeSnapshot(JSON.parse(zlib.gunzipSync(packed))),V=require('./site/radar-viz.js'),snapshot=V.visitorSnapshot(full);
const rules=JSON.parse(fs.readFileSync(path.join(__dirname,'validation/task-measurements-v8-real.json')));
if(rules.snapshot_id!==snapshot.snapshot_id)throw Error('TASK_SNAPSHOT_MISMATCH');
const pick=(row,keys)=>Object.fromEntries(keys.filter(k=>row[k]!==undefined).map(k=>[k,row[k]]));
const fallbackSources=new Set();
const groups=snapshot.index.groups.map(g=>{
 const extra=!rules.groups[g.group_id]?pick(g,['metric','metric_role_context']):{};
 if(!rules.groups[g.group_id]&&!g.blocked_reasons?.length&&!g.extraction_in_progress)fallbackSources.add(JSON.stringify([g.paper_id,g.benchmark_id]));
 return {...pick(g,['group_id','paper_id','benchmark_id','benchmark_identity','direction','blocked_reasons','extraction_in_progress','metric_role']),...extra,scores:(g.scores||[]).map(s=>pick(s,['model_canonical','value_numeric']))};
});
const task={format:'radar-static-task-evidence-v1',snapshot_id:snapshot.snapshot_id,task_method_version:8,
  measurements:{schema_version:rules.schema_version,snapshot_id:rules.snapshot_id,groups:Object.fromEntries(groups.filter(g=>rules.groups[g.group_id]).map(g=>[g.group_id,pick(rules.groups[g.group_id],['models','aliases','capabilities','domains','tasks'])]))},
  snapshot:{snapshot_id:snapshot.snapshot_id,generated_at:snapshot.generated_at,window:snapshot.window,status:snapshot.status,
    task_evidence_only:true,detail_loaded:false,visitor_catalog_filtered:true,model_registry:snapshot.model_registry,observations:[],
    benchmarks:snapshot.benchmarks.map(b=>pick(b,['paper_id','benchmark_id','benchmark_name','benchmark_identity','directory_identity','catalog_labels','catalog_label_sources',...(fallbackSources.has(JSON.stringify([b.paper_id,b.benchmark_id]))?['enrichment']:[])])),
    index:{models:snapshot.index.models.map(m=>pick(m,['model_canonical','general_model_issue'])),groups}}};
const bytes=zlib.gzipSync(Buffer.from(JSON.stringify(task)),{level:9});
const sha=crypto.createHash('sha256').update(bytes).digest('hex'),asset=`snapshot/${snapshot.snapshot_id}/task-evidence-${sha.slice(0,16)}.json.gz`;
fs.writeFileSync(path.join(site,asset),bytes);
manifest.task_evidence={format:task.format,path:asset,bytes:bytes.length,sha256:sha,snapshot_id:task.snapshot_id,task_method_version:8};
fs.writeFileSync(manifestPath,JSON.stringify(manifest));
const report={snapshot_id:snapshot.snapshot_id,task_method_version:8,task_evidence_bytes:bytes.length,full_archive_bytes:packed.length,archive_reduction:1-bytes.length/packed.length,groups:groups.length,models:task.snapshot.index.models.length,raw_scores_unchanged:true};
fs.writeFileSync(path.join(__dirname,'task-loading-validation.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
