"""Versioned probability scale, independent of ranking visibility and roster."""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

METHOD = 'fixed-reference-panel-v1'

@lru_cache(None)
def reference_panel():
    raw=Path(__file__).with_name('normalization-reference-panel.json').read_bytes()
    panel=json.loads(raw)
    panel['sha256']=hashlib.sha256(raw).hexdigest()
    return panel

def expected_score(elo, reference_elo):
    delta=(elo-reference_elo)*math.log(10)/400
    z=math.exp(-abs(delta))
    return 1/(1+z) if delta>=0 else z/(1+z)

def normalize(rows, *, elo_key='elo', score_key='score', panel=None):
    """Apply a monotone mapping; never refit, filter rows, or reselect anchors.

    A missing reference makes this scale unavailable rather than silently
    changing the denominator. Original strengths and source counts survive.
    """
    panel=panel or reference_panel()
    references=panel['references']
    keys=[(r['model'],r.get('setting','')) for r in references]
    if len(set(keys))!=len(keys) or not references:
        raise ValueError('Empty or duplicated reference panel')
    weights=[r['weight'] for r in references]
    if any(not math.isfinite(w) or w<=0 for w in weights) or not math.isclose(math.fsum(weights),1.,abs_tol=1e-12):
        raise ValueError('Reference weights must be positive and sum to one')
    by_node={(r['model'],r.get('setting','')):r for r in rows}
    if len(by_node)!=len(rows):raise ValueError('Duplicate fitted identities')
    missing=[list(k) for k in keys if k not in by_node or not math.isfinite(by_node[k][elo_key])]
    audit=dict(method=METHOD,version=panel['version'],panel_sha256=panel.get('sha256'),
               reference_count=len(keys),references=references,missing=missing,
               status='REFERENCE_PANEL_INCOMPLETE' if missing else 'READY',
               interpretation='Expected match score against the frozen reference panel; ties count as one half. Not benchmark accuracy.',
               cross_snapshot_comparability='Relative estimates; reference strengths are refitted, so this is not a fixed historical ability scale.')
    for row in rows:
        if not math.isfinite(row[elo_key]):raise ValueError('Non-finite model strength')
        row[score_key]=None if missing else 100*math.fsum(w*expected_score(row[elo_key],by_node[k][elo_key]) for k,w in zip(keys,weights))
    return audit

def validate(rows, audit, *, elo_key='elo', score_key='score'):
    copy=[dict(r) for r in rows]
    panel=dict(version=audit['version'],references=audit['references'],sha256=audit.get('panel_sha256'))
    recalculated=normalize(copy,elo_key=elo_key,score_key=score_key,panel=panel)
    assert audit['status']==recalculated['status'] and audit['missing']==recalculated['missing']
    for expected,actual in zip(copy,rows):
        assert expected[score_key] is None and actual[score_key] is None or (
            expected[score_key] is not None and actual[score_key] is not None and
            math.isclose(expected[score_key],actual[score_key],abs_tol=1e-10))
