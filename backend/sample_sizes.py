"""Source-scoped sample counts. Never infer n from runs, tokens or score rows."""
import csv
import hashlib
import io
import json
from pathlib import Path

REGISTRY = Path(__file__).with_name('benchmark-sample-sizes.json')

def entries():
    return json.loads(REGISTRY.read_text(encoding='utf8'))['entries']

def key(row):
    return tuple(str(row.get(k) or '') for k in ('paper_id','table_id','metric'))

def evidence(row, registry):
    source=row.get('reviewed_source') or {}
    caption=source.get('caption') or row.get('scope_evidence') or ''
    digest=hashlib.sha256(caption.encode()).hexdigest()
    for item in registry.get(key(row),[]):
        if digest == item['caption_sha256'] or source.get('table_sha256') == item['table_sha256']:
            return item
    return None

def annotate(snapshot):
    records=entries();registry={}
    for item in records: registry.setdefault(key(item),[]).append(item)
    groups=snapshot.get('score_groups',snapshot.get('index',{}).get('groups',[]))
    observations=snapshot.get('observations',[])
    obs_by_id={r['observation_id']:r for r in observations}
    for group in groups:
        proof=evidence(group,registry)
        if not proof:
            candidates=[evidence(obs_by_id.get(oid,{}),registry) for s in group.get('scores',[]) for oid in s.get('observation_ids',[])]
            known=[p for p in candidates if p]
            if known and all(p==known[0] for p in known): proof=known[0]
        group['evaluation_n']=proof['n'] if proof else None
        group['sample_size']=proof
    for row in observations:
        proof=evidence(row,registry)
        row['evaluation_n']=proof['n'] if proof else None
        row['sample_size']=proof
    # Counts remain attached to the source metric. A benchmark may have different subsets.
    for bench in snapshot.get('benchmarks',[]):
        matches=[r for r in records if r['paper_id']==bench['paper_id'] and r['benchmark_id']==bench['benchmark_id']]
        bench['sample_sizes']=matches
        bench['evaluation_n']=None
    return records

def publish(snapshot,root,site):
    records=annotate(snapshot)
    artifact=dict(version=1,snapshot_id=snapshot['snapshot_id'],score_weighting='unchanged',
        scope='source metric evaluated subset; not a benchmark-wide count',entries=records)
    raw=json.dumps(artifact,ensure_ascii=False,separators=(',',':')).encode()
    digest=hashlib.sha256(raw).hexdigest();path=root/('sample-sizes-'+digest[:16]+'.json');path.write_bytes(raw)
    out=io.StringIO(newline='');columns=['paper_id','benchmark_id','table_id','metric','n','unit','scope','dataset_total_n','repetitions','source_url','source_quote','table_sha256']
    writer=csv.DictWriter(out,fieldnames=columns,extrasaction='ignore');writer.writeheader()
    for row in records:
        writer.writerow({k:("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in row.items()})
    csv_path=path.with_suffix('.csv');csv_path.write_text('\ufeff'+out.getvalue(),encoding='utf8')
    return dict(path=path.relative_to(site).as_posix(),sha256=digest,bytes=len(raw),
        csv_path=csv_path.relative_to(site).as_posix(),entries=len(records))
