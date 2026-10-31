import json,gzip,sys
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).parent;sys.path.insert(0,'D:/FDU/benchmark-radar')
import recent_benchmarks
recent_benchmarks.__path__.insert(0,str(ROOT.parent/'backend/task_rules'))
from recent_benchmarks.catalog_task_scoring import score_task
from recent_benchmarks.task_measurement_policy import modality_matches
d=json.loads(gzip.decompress((ROOT/'task-comprehensive-task_inputs-20261101.json.gz').read_bytes()));profiles=json.loads((ROOT/'task-v11-live-profiles.json').read_text(encoding='utf-8'))
sources={(b['paper_id'],b['benchmark_id']):b for b in d['catalog']};report={'snapshot_id':d['snapshot_id'],'cases':{}}
for name,c in profiles['cases'].items():
 if c['status']!='PASS':raise AssertionError(name)
 r=score_task(deepcopy(d['index']),d['catalog'],c['profile'],as_of=d['window']['end'])
 assert all(modality_matches(c['profile']['constraints']['modality'],sources[b['paper_id'],b['benchmark_id']]['catalog_labels']['modalities'])for b in r['benchmark_matches'])
 report['cases'][name]={'benchmarks':r['matched_benchmarks'],'models':len({m['model_canonical']for m in r['models']}),'evidence_summary':r['evidence_summary'],'constraints':c['profile']['constraints']}
 (ROOT/f'task-v11-fresh-{name}.json.gz').write_bytes(gzip.compress(json.dumps({'snapshot_id':d['snapshot_id'],'task_index':r},ensure_ascii=False).encode()))
 (ROOT/'task-v11-fresh-replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(name,r['matched_benchmarks'],report['cases'][name]['models'],flush=True)
