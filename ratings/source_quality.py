"""Source semantics gate shared by main and capability ranking builders.

Raw inputs are never mutated. Versioned source repairs precede identity and
pair construction; pair-specific overlap removal runs AFTER board selection.
No model strength, manufacturer or expected ordering enters these rules.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re

REGISTRY = Path(__file__).with_name('source-quality-registry.json')

@lru_cache(None)
def registry():
    rules = json.loads(REGISTRY.read_text(encoding='utf8'))
    supplemental = json.loads(REGISTRY.with_name('opus-source-registry.json').read_text(encoding='utf8'))
    for gid, rule in supplemental['groups'].items():
        rules['groups'].setdefault(gid, {}).update(rule)
    rules['version'] += '|' + json.loads(REGISTRY.with_name('source-integrity-registry.json').read_text(encoding='utf8'))['version'] + '|column-direction-guard-v1'
    return rules

def cell_signature(group):
    cells = sorted((s['model_canonical'], s['value_numeric']) for s in group.get('scores', []))
    return sha256(json.dumps(cells, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest() if cells else None

def norm(value):
    return ' '.join((value or '').casefold().split())

def _efforts(value):
    if norm(value) in {'none','minimal','low','medium','high','xhigh','max'}:
        return {norm(value)}
    return set(re.findall(r'(?:reasoning(?: effort)?\s*[:=]?\s*|\()\b(none|minimal|low|medium|high|xhigh|max)\b', (value or '').casefold()))

def prepare_data(data, rules=None):
    """Return a provenance-bearing derived view; repeated application is safe."""
    rules = rules or registry()
    if data.get('source_quality_policy'):
        if data['source_quality_policy'] != rules['version']:
            raise ValueError('Rebuild source quality from original inputs for a policy upgrade')
        return deepcopy(data), deepcopy(data['source_quality_audit'])
    out = deepcopy(data)
    groups = out['index']['groups']
    report = {'policy': rules['version'], 'raw_input_unchanged': True, 'events': []}
    projections = out.get('measurements', {}).get('groups', {})
    guarded = {}
    resource_names = set(rules['resource_metrics'])
    for group in groups:
        gid = group['group_id']
        spec = rules['groups'].get(gid)
        quality = {'policy': rules['version'], 'eligible': True}
        group['source_quality'] = quality
        if spec:
            matches = (all(group.get(k) == spec[k] for k in ('paper_id', 'table_id', 'metric'))
                       and spec.get('cell_sha256') is not None
                       and cell_signature(group) == spec['cell_sha256']
                       and ('caption' not in spec or norm(group.get('metric_role_context', '')) == norm(spec['caption'])))
            guarded[gid] = matches
            if not matches:
                quality.update(eligible=False, reason='reviewed_source_changed_requires_recheck')
            else:
                if spec.get('exclude_reason'):
                    quality.update(eligible=False, reason=spec['exclude_reason'])
                if spec.get('categories') is not None:
                    quality['categories'] = spec['categories']
                if spec.get('direction'):
                    quality['original_direction'] = group.get('direction')
                    group['direction'] = spec['direction']
                    quality['direction_corrected'] = group['direction'] != quality['original_direction']
                required = spec.get('required_setting')
                if required:
                    previous = group.get('model_setting', '')
                    wanted = _efforts(required)
                    conflicts = bool(_efforts(previous) - wanted) if wanted else bool(previous and norm(previous) != norm(required))
                    conflicts |= any(bool(_efforts(s['model_canonical']) - wanted) for s in group.get('scores', [])) if wanted else False
                    if wanted:
                        conflicts |= bool(_efforts(group.get('source_condition_key', '')) - wanted)
                    if conflicts:
                        quality.update(eligible=False, reason='explicit_configuration_conflict')
                    else:
                        quality['original_model_setting'] = previous
                        # Preserve extra experiment conditions while filling a
                        # missing dimension; never erase an existing setting.
                        group['model_setting'] = previous if norm(required) in norm(previous) else '; '.join(filter(None, [previous, required]))
                        quality['configuration_corrected'] = group['model_setting'] != previous
        if norm(group.get('metric')) in resource_names:
            quality.update(eligible=False, reason='resource_usage_not_capability')
        if group.get('metric_role') in {'EFFICIENCY','METADATA','STATISTIC','DERIVED_STATISTIC','INTERVENTION_EFFECT','TARGET_MODEL_DIAGNOSTIC','RELATIONAL_OR_DAMAGED_AXIS'}:
            quality.update(eligible=False, reason='declared_non_performance_measurement')
        if not quality['eligible'] or quality.get('direction_corrected') or quality.get('configuration_corrected'):
            report['events'].append({'group_id': gid, 'paper_id': group['paper_id'], **quality})
    by_id = {g['group_id']: g for g in groups}
    for gid, spec in rules['groups'].items():
        if gid not in by_id or not guarded.get(gid):
            continue
        by_id[gid]['source_quality']['aggregate_parents'] = [p for p in spec.get('aggregate_parents', []) if guarded.get(p) and by_id[p]['source_quality']['eligible']]
    # Replacements require the explicit reviewed source groups. Extra singleton
    # columns (which never produced comparisons) do not block a transcription.
    original_groups = list(groups)
    for replacement in rules.get('replacements', []):
        originals = [g for g in original_groups if g['table_id'] == replacement['source_table'] and g['paper_id'] == replacement['paper_id']]
        if not originals:
            continue
        required = replacement.get('source_groups', [g['group_id'] for g in originals])
        if not required or not all(guarded.get(gid) for gid in required):
            report['events'].append({'group_id': replacement['group_id'], 'reason': 'replacement_source_changed_requires_recheck', 'eligible': False})
            continue
        template = originals[0]
        derived = deepcopy(template)
        derived.update(group_id=replacement['group_id'], metric=replacement['metric'], direction=replacement['direction'], model_setting=replacement['model_setting'], source_condition_key='',
                       source_quality={'policy': rules['version'], 'eligible': True, 'verified_reextraction': True, 'source_url': replacement['source_url'], 'html_sha256': replacement['html_sha256'], 'replaces_table_id': replacement['source_table'], 'categories': replacement.get('categories'), 'main_fit': replacement.get('main_fit', True)})
        derived['scores'] = [{'model_canonical': s['model'], 'value_numeric': s['value'], 'observation_ids': [f"{replacement['group_id']}:{i}"],
                              'task_source_records': [{'observation_id': f"{replacement['group_id']}:{i}", 'model_raw': s['model'], 'source_row': i + 2, 'source_column': replacement['source_column'], 'source_url': replacement['source_url']}]} for i, s in enumerate(replacement['scores'])]
        groups.append(derived)
        if projections:
            # Preserve classification eligibility and measured models explicitly.
            source_meta = next((projections[g['group_id']] for g in originals if g['group_id'] in projections and projections[g['group_id']].get('capabilities')), None)
            if source_meta is not None:
                projections[derived['group_id']] = {**deepcopy(source_meta), 'models': [s['model_canonical'] for s in derived['scores']]}
            else:
                derived['source_quality'].update(eligible=False, reason='replacement_measurement_scope_not_available')
        report['events'].append({'group_id': derived['group_id'], 'paper_id': derived['paper_id'], **derived['source_quality']})
    from source_integrity import apply_repairs
    report['integrity_repairs'] = apply_repairs(out)
    from metric_semantics import audit_directions
    report['direction_conflicts'] = audit_directions(out['index']['groups'])
    report['direction_check_counts'] = dict(Counter(g['metric_direction_check']['status'] for g in out['index']['groups']))
    report['counts'] = dict(Counter(e.get('reason') or ('verified_reextraction' if e.get('verified_reextraction') else 'configuration_or_direction') for e in report['events']))
    out['source_quality_policy'] = rules['version']
    out['source_quality_audit'] = report
    return out, report

def attach_provenance(records, groups):
    """Carry only the fields needed for within-board overlap checks."""
    by_id = {g['group_id']: g for g in groups}
    result = []
    for r in records:
        g = by_id[r['group_id']]
        cells = {}
        for s in g.get('scores', []):
            key = (s['model_canonical'], s.get('dedup_condition', g.get('model_setting', '') or g.get('source_condition_key', '')))
            if s.get('observation_ids'):
                cells[key] = tuple(sorted(s['observation_ids']))
        unit = tuple(sorted((cells.get(tuple(r['a']), ()), cells.get(tuple(r['b']), ()))))
        result.append({**r, 'source_quality': deepcopy(g.get('source_quality', {})),
                       'source_cell_pair': unit if all(unit) else None})
    return result

def filter_board_records(records, *, board='Main'):
    """Suppress only overlapping evidence for the SAME configured pair.

    Children survive in a specialist board when their parent is absent there.
    Equal numeric values, model generation, and vendor never imply duplication.
    """
    def pair(r): return tuple(sorted((tuple(r['a']), tuple(r['b']))))
    active = [r for r in records if r.get('source_quality', {}).get('eligible', True) and (board != 'Main' or r.get('source_quality', {}).get('main_fit', True))]
    present = {(r['paper_id'], r['group_id'], pair(r)) for r in active}
    output, audit, seen = [], [], {}
    for r in active:
        p = pair(r)
        parents = r.get('source_quality', {}).get('aggregate_parents', [])
        if any((r['paper_id'], parent, p) in present for parent in parents):
            audit.append({'group_id': r['group_id'], 'paper_id': r['paper_id'], 'reason': 'same_pair_aggregate_overlap'})
            continue
        # Repeated representations of the very same measured cells are one
        # observation. A different paper or condition remains independent.
        unit = r.get('source_cell_pair')
        key = (r['paper_id'], p, tuple(tuple(x) for x in unit)) if unit else (r['paper_id'], r['group_id'], p)
        y = r['y'] if tuple(r['a']) == p[0] else 1 - r['y']
        if key in seen:
            if seen[key] != y:
                raise ValueError('Conflicting outcomes for the same source cells; review required')
            audit.append({'group_id': r['group_id'], 'paper_id': r['paper_id'], 'reason': 'same_source_cells_repeated'})
            continue
        seen[key] = y
        output.append(r)
    return output, audit
