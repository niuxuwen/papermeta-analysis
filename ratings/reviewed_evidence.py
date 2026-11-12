"""Merge source-reviewed measurements into each fresh service publication.

This is an evidence layer, not a fallback snapshot. Service data stays intact;
reviewed additions retain their date, cell coordinates and original provenance.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent

def signature(group):
    value = {k: group.get(k) for k in ('paper_id', 'table_id', 'metric', 'model_setting', 'direction')}
    value['cells'] = sorted((s['model_canonical'], s['value_numeric']) for s in group['scores'])
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def load_pack():
    manifest = json.loads((ROOT/'reviewed-evidence-manifest.json').read_text(encoding='utf8'))
    raw = (ROOT/'reviewed-evidence.json.gz').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['sha256'] and len(raw) == manifest['bytes']
    return json.loads(gzip.decompress(raw)), manifest

def timestamp(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

def coordinates(group, score):
    rows = score.get('task_source_records', [])
    cells = [(r.get('source_row'), r.get('source_column')) for r in rows]
    if cells and all(type(i) is int and type(j) is int for i,j in cells):
        return tuple(sorted({f"{group['paper_id']}:{group['table_id']}:{i}:{j}" for i,j in cells}))
    return ()

def merge(data, papers, pack=None, manifest=None):
    if pack is None:
        pack, manifest = load_pack()
    out = deepcopy(data)
    papers = dict(papers)
    groups = out['index']['groups']
    by_id = {g['group_id']:g for g in groups}
    events = []
    window = data['window'].get('paper', data['window'])
    start, end = timestamp(window['start']), timestamp(window['end'])
    live_cells = {}
    for g in groups:
        for s in g['scores']:
            for key in coordinates(g,s):
                live_cells.setdefault(key,set()).add(s['value_numeric'])
    accepted = set()
    for original in pack['groups']:
        gid, pid = original['group_id'], original['paper_id']
        p = pack['papers'][pid]
        if not start <= timestamp(p['paper_first_published']) < end:
            events.append(dict(group_id=gid,paper_id=pid,reason='outside_current_publication_window'))
            continue
        if gid in by_id:
            events.append(dict(group_id=gid,paper_id=pid,reason='already_in_service' if signature(original)==signature(by_id[gid]) else 'changed_service_group_preferred'))
            continue
        # A different value in an existing source cell requires renewed review.
        if any(live_cells[key] != {s['value_numeric']} for s in original['scores'] for key in coordinates(original,s) if key in live_cells):
            events.append(dict(group_id=gid,paper_id=pid,reason='changed_service_cell_requires_review'))
            continue
        g = deepcopy(original)
        g['reviewed_evidence_version'] = pack['version']
        g['reviewed_source_url'] = g.get('reviewed_source',{}).get('url') or 'https://arxiv.org/abs/'+p['arxiv_id']
        groups.append(g); by_id[gid]=g; accepted.add(gid)
        papers.setdefault(pid,p)
    # Only exact, previously reviewed misextractions are replaced. Changed live
    # sources are never silently removed by an old review.
    for amendment in pack.get('amendments', []):
        if not set(amendment['replacement_group_ids']) <= by_id.keys():
            continue
        for gid in amendment['old_group_ids']:
            if gid in by_id and signature(by_id[gid]) == amendment['old_signatures'][gid]:
                by_id[gid].setdefault('blocked_reasons',[]).append('replaced_by_verified_source_cells')
                events.append(dict(group_id=gid,paper_id=by_id[gid]['paper_id'],reason='verified_source_replacement'))
    classified = 0
    for g in groups:
        label = pack['classifications'].get(g['group_id'])
        if label and label['source_signature']==signature(g):
            g['reviewed_categories'] = label['categories']
            classified += 1
        # Stable source coordinates unify overlap across extraction systems.
        for s in g['scores']:
            keys=coordinates(g,s)
            if keys:
                s['review_original_observation_ids']=s.get('observation_ids',[])
                s['observation_ids']=list(keys)
    audit=dict(version=pack['version'],reviewed_at=pack['reviewed_at'],service_snapshot=data['snapshot_id'],
               evidence_sha256=(manifest or {}).get('sha256'),attested_review_papers=pack['attested_verified_papers'],
               added_groups=len(accepted),added_papers=len({by_id[g]['paper_id'] for g in accepted}),
               classified_groups=classified,event_counts=dict(Counter(e['reason'] for e in events)),events=events)
    import sys
    sys.path.insert(0,str(ROOT.parent/'backend'))
    from sample_sizes import annotate
    annotate(out)
    out['reviewed_evidence_audit']=audit
    return out,papers,audit

def publish_pack(site, snapshot):
    _, manifest=load_pack()
    relative=f"snapshot/{snapshot}/reviewed-evidence-{manifest['sha256'][:16]}.json.gz"
    destination=site/relative
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes((ROOT/'reviewed-evidence.json.gz').read_bytes())
    return dict(path=relative,**manifest)
