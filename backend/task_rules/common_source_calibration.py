"""Finite, disclosed calibration from repeated observed source comparisons.

This is a data-derived regularizer, not additional observations. Manufacturer,
model age and version order are never inputs. Conflicting source directions
receive no such penalty. The same finite direct penalty applies to every pair.
"""
from collections import defaultdict
from itertools import combinations
from statistics import fmean
import math

POLICY = 'vendor-blind-repeated-source-calibration-v2'
DIRECT_STRENGTH = 2.0
WITHIN_VENDOR_STRENGTH = 0.0
MARGIN_FRACTION = .25
MIN_PAPERS = 2
MIN_CONTRAST = .01
CALIBRATION = {
    'policy': POLICY, 'direct_strength': DIRECT_STRENGTH,
    'within_vendor_strength': WITHIN_VENDOR_STRENGTH,
    'margin_fraction': MARGIN_FRACTION, 'min_independent_papers': MIN_PAPERS,
    'min_absolute_target_contrast': MIN_CONTRAST,
    'development_snapshot': 'c88df5aa4ebdd38faefa8723',
    'selection': 'Lowest source log-loss and Brier among predeclared hybrid candidates in four whole-source-family development folds; parameters frozen before the independent-source evaluation.',
    'independent_snapshot': 'a63cbc3fb29b915f082f0a32',
    'independent_validation': {
        'reserved_groups': 197, 'reserved_paper_families': 36,
        'covered_all_pairs': 2286, 'covered_within_vendor_pairs': 382,
        'all_direction_agreement': [0.6556014705410853, 0.6605984790880938],
        'within_vendor_direction_agreement': [0.6337621406371406, 0.6550121406371406],
        'all_logloss': [0.6397428152900898, 0.6218200538037473],
        'within_vendor_logloss': [0.6629472485387405, 0.6431144882031733],
    },
    'limitations': 'Source comparison agreement is not model accuracy. The reserved sample is small and only covers models present in the old reference cohort. Default-setting selection does not validate every experimental setting. No universal or newest-model-first ordering guarantee.',
    'vendor_grouping_used': False, 'model_age_or_release_order_used': False,
    'hard_projection': False,
}


# Historical v1 evaluation is not evidence that this revised policy improves accuracy.
CALIBRATION.pop('independent_validation', None)
CALIBRATION.update(selection='Frozen direct strength 2 retained; manufacturer-only hinge removed without retuning.',
    development_snapshot=None, independent_snapshot=None,
    limitations='Vendor-blind policy requires its own held-out assessment; no newest-model-first guarantee.')


def pair_summaries(groups, names, target):
    """One mean per benchmark and original paper family; no repeated-cell votes."""
    by = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    names, seen = set(names), set()
    for g in groups:
        rows = sorted((s for s in g['scores'] if s['model_canonical'] in names),
                      key=lambda s: s['model_canonical'])
        paper = g.get('calibration_paper_identity', 'paper:' + g['paper_id'])
        bench = g.get('benchmark_identity', g['benchmark_id'])
        for a, b in combinations(rows, 2):
            key = a['model_canonical'], b['model_canonical']
            fingerprint = (key, paper, g['table_id'], g['metric'], g.get('row_key'),
                           a['value_numeric'], b['value_numeric'])
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            delta = (a['value_numeric']-b['value_numeric'])*(1 if g['direction']=='higher' else -1)
            by[key][paper][bench].append((target(g,a,b), .5 if not delta else float(delta>0), g['group_id']))
    result = []
    for (a,b), papers in by.items():
        proof = []
        for paper, benches in papers.items():
            proof.append(dict(paper=paper,
                target=fmean(fmean(r[0] for r in rows) for rows in benches.values()),
                win_fraction=fmean(fmean(r[1] for r in rows) for rows in benches.values()),
                groups=[r[2] for rows in benches.values() for r in rows]))
        same_direction = (all(p['target']>=.5 and p['win_fraction']>=.5 for p in proof)
                          or all(p['target']<=.5 and p['win_fraction']<=.5 for p in proof))
        result.append(dict(a=a,b=b,papers=len(proof),target=fmean(p['target'] for p in proof),
            vote=fmean(p['win_fraction'] for p in proof), consistent=same_direction,sources=proof))
    return result


def attach(layout, groups, names, eligible, target, source_factor):
    """Add regularization and assign its score contributions to original families."""
    eligible, pos = set(eligible), {n:i for i,n in enumerate(names)}
    family_by_paper = {g['paper_id']:g.get('calibration_paper_identity','paper:'+g['paper_id']) for g in groups}
    clusters = defaultdict(list)
    for paper, rows in layout['clusters'].items():
        clusters[family_by_paper.get(paper,paper)].extend(rows)
    rules, quadratic = [], []
    for r in pair_summaries(groups,names,target):
        if (r['a'] not in eligible or r['b'] not in eligible or r['papers']<MIN_PAPERS
                or not r['consistent'] or abs(r['target']-.5)<MIN_CONTRAST):
            continue
        a,b = pos[r['a']],pos[r['b']]
        support_factor = source_factor*r['papers']/(r['papers']+2)
        w = DIRECT_STRENGTH*support_factor
        layout['edges'].append((a,b,r['target'],w))
        for p in r['sources']:
            clusters[p['paper']].append((a,b,p['target'],w/r['papers']))
        rules.append(dict(r,within_vendor=False,winner=None,loser=None,
                          direct_weight=w,consistency_weight=0.,margin=0.))
    layout['clusters'] = dict(clusters)
    layout['quadratic_edges'] = quadratic
    return dict(enabled=True,policy=POLICY,calibration=CALIBRATION,rules=rules,
                direct_terms=len(rules),within_vendor_terms=len(quadratic),hard_projection=False)


def cluster_gradients(audit, pos, theta, scale):
    """Conditional hinge gradients; support selection uncertainty is not inferred."""
    result = defaultdict(list)
    for r in audit['rules']:
        if not r['within_vendor']:
            continue
        a,b = pos[r['winner']],pos[r['loser']]
        gradient = -r['consistency_weight']*max(0.,r['margin']-theta[a]+theta[b])*scale
        for p in r['sources']:
            result[p['paper']].append((a,b,gradient/r['papers']))
    return result
