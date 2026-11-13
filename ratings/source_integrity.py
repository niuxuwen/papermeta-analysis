"""Guarded, source-reviewed roster repairs; preserve raw evidence and audit gaps."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def signature(group):
    cells=sorted((s['model_canonical'],s['value_numeric']) for s in group['scores'])
    return hashlib.sha256(json.dumps(cells,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def reconcile_roster(expected, scores, excluded=None):
    """Every original model row needs a result or an explicit exclusion reason."""
    actual={s.get('source_model_name',s['model_canonical']) for s in scores}
    excluded=excluded or {}
    explained={name for name,reason in excluded.items() if isinstance(reason,str) and reason.strip()}
    return dict(missing=sorted(set(expected)-actual-explained),
                unexpected=sorted(actual-set(expected)),
                explained_exclusions={k:excluded[k] for k in sorted(explained)})


def apply_repairs(data, registry=None):
    if registry is None:
        registry=json.loads(Path(__file__).with_name('source-integrity-registry.json').read_text(encoding='utf8'))
    events=[];projections=data.get('measurements',{}).get('groups',{})
    additions=[];existing={g['group_id'] for g in data['index']['groups']}
    for g in list(data['index']['groups']):
        spec=registry['groups'].get(g['group_id'])
        if not spec:continue
        if g.get('source_integrity_revision')==registry['version']:continue
        if (g['paper_id'],g['table_id'],signature(g))!=(spec['paper_id'],spec['table_id'],spec['cell_sha256']):
            # Changed sources cannot inherit an old repair. Only this group is held.
            g.setdefault('source_quality',{}).update(eligible=False,reason='integrity_source_changed_requires_recheck')
            events.append(dict(group_id=g['group_id'],status='SOURCE_CHANGED'));continue
        if spec.get('annotation_only'):
            g['metric_role']='DERIVED_STATISTIC'
            g.setdefault('source_quality',{}).update(eligible=False,reason='derived_delta_annotation_not_independent_score')
        if spec.get('scores'):
            previous=deepcopy(g['scores']);g['scores']=deepcopy(spec['scores'])
            g['source_roster_audit']=reconcile_roster(spec['expected_models'],g['scores'])
            assert not g['source_roster_audit']['missing'] and not g['source_roster_audit']['unexpected']
            g['pre_repair_scores']=previous
            if g['group_id'] in projections:
                projections[g['group_id']]['models']=[s['model_canonical'] for s in g['scores']]
        if spec.get('metadata'):
            allowed={'metric','direction','row_key','metric_role_context','evaluation_n','evaluation_condition'}
            assert set(spec['metadata'])<=allowed
            g['pre_repair_metadata']={k:deepcopy(g.get(k)) for k in spec['metadata']}
            g.update(deepcopy(spec['metadata']))
        if spec.get('aggregate_parents'):
            g.setdefault('source_quality',{})['aggregate_parents']=list(spec['aggregate_parents'])
        for extra in spec.get('additional_groups',[]):
            if extra['group_id'] in existing:continue
            ng=deepcopy(g)
            for key in ('pre_repair_scores','pre_repair_metadata','records_fingerprint'):ng.pop(key,None)
            ng.update(deepcopy(extra))
            ng['source_roster_audit']=reconcile_roster(spec['expected_models'],ng['scores'])
            assert not ng['source_roster_audit']['missing'] and not ng['source_roster_audit']['unexpected']
            ng['source_integrity_revision']=registry['version']
            ng['source_integrity_evidence']=deepcopy(extra.get('source_integrity_evidence') or {k:spec[k] for k in ('source_url','source_sha256','explanation')})
            additions.append(ng);existing.add(ng['group_id'])
            if g['group_id'] in projections:
                projections[ng['group_id']]=deepcopy(projections[g['group_id']])
                projections[ng['group_id']]['models']=[s['model_canonical'] for s in ng['scores']]
        if spec.get('evidence_source_id'):
            g.setdefault('source_quality',{})['evidence_source_id']=spec['evidence_source_id']
        g['source_integrity_revision']=registry['version']
        g['source_integrity_evidence']={k:spec[k] for k in ('source_url','source_sha256','explanation')}
        events.append(dict(group_id=g['group_id'],status='REPAIRED',annotation_only=spec.get('annotation_only',False),models=len(g['scores'])))
    data['index']['groups'].extend(additions)
    return events
