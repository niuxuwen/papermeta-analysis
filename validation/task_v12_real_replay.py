import json,gzip,sys,time
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).parent;sys.path.insert(0,'D:/FDU/benchmark-radar')
import recent_benchmarks
recent_benchmarks.__path__.insert(0,str(ROOT.parent/'backend/task_rules'))
from recent_benchmarks.catalog_task_scoring import score_task
from recent_benchmarks.task_measurements import projection,source_model_identity_issue
from recent_benchmarks.task_measurement_policy import task_metric_role,modality_matches
from audit_task_rankings_20261031 import aggregate
d=json.loads(gzip.decompress((ROOT/'task-readiness-followup-inputs.json.gz').read_bytes()));old=json.loads((ROOT/'task-readiness-followup-20261101.json').read_text(encoding='utf-8'))
groups={g['group_id']:g for g in d['index']['groups']};sources={(b['paper_id'],b['benchmark_id']):b for b in d['catalog']};report={'snapshot_id':d['snapshot_id'],'method':12,'model_calls':0,'cases':{}}
meta=projection(d['index'],d['catalog'],d['snapshot_id']);(ROOT/'task-v12-measurements-real.json.gz').write_bytes(gzip.compress(json.dumps(meta,ensure_ascii=False).encode(),mtime=0))
for name,previous in old['cases'].items():
 p=json.loads(gzip.decompress((ROOT/f'task-v11-result-{name}.json.gz').read_bytes()))['task_index']['profile']
 r=score_task(deepcopy(d['index']),d['catalog'],p,as_of=d['window']['end']);a=aggregate({'task_index':r})
 assert all(not source_model_identity_issue(m['model_canonical'])for m in r['models'])
 assert all(modality_matches(p['constraints']['modality'],sources[b['paper_id'],b['benchmark_id']]['catalog_labels']['modalities'])for b in r['benchmark_matches'])
 for m in r['models']:
  assert 0<=m['score']<=100
  for c in m['score_components']:
   assert task_metric_role(groups[c['group_id']])=='PERFORMANCE'
   assert c['raw_value']in[s['value_numeric']for s in groups[c['group_id']]['scores']if s['model_canonical']==m['model_canonical']]
 report['cases'][name]={'before':{k:previous[k]for k in ['models','benchmarks','panels']},'after':{k:a[k]for k in ['models','benchmarks','panels','same_vendor_pairs_with_shared_sources','strict_same_vendor_dominance_conflicts']},'excluded_identity_names':sorted({e['model_canonical']for e in r['exclusions']if e.get('reason','').startswith('model_identity_')}),'evidence_summary':r['evidence_summary']}
 (ROOT/f'task-v12-result-{name}.json.gz').write_bytes(gzip.compress(json.dumps({'snapshot_id':d['snapshot_id'],'task_index':r},ensure_ascii=False).encode(),mtime=0))
 (ROOT/'task-v12-real-replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(name,previous['models'],'->',a['models'],a['benchmarks'],'benchmarks',flush=True)
