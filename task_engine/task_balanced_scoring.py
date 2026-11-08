from __future__ import annotations

from collections import defaultdict

from statistics import fmean, median

import math

from .score_normalization import validate_scale

def prepare_contrast_scales(groups):
    """A two-value SD cannot establish a meaningful continuous margin.

    Prefer a verified range (quarter range as the fixed working contrast unit),
    otherwise a leave-group-out >=3-model SD from the exact same source,
    benchmark, metric, setting and comparison condition. Without either,
    expose an ordinal-only fallback with half information weight. Its target
    is .75/.25/.5, not a claim about the magnitude of the raw difference.
    """
    peers = defaultdict(list)
    def identity(g):
        return tuple(g.get(k, '') for k in ('paper_id', 'table_id', 'benchmark_id',
                     'metric', 'model_setting', 'comparison_key', 'source_condition_key', 'direction'))
    for g in groups:
        ref = g['reference_profile']
        if ref['reference_count'] >= 3 and ref['standard_deviation'] > 0:
            peers[identity(g)].append((g['group_id'], ref['standard_deviation']))
    for g in groups:
        ref = g['reference_profile']; sd = ref['standard_deviation']
        ref.update(contrast_scale=sd, contrast_method='SOURCE_REFERENCE_SD', information_weight=1., scale_source_groups=[])
        if ref['reference_count'] != 2:
            continue
        scale, _ = validate_scale(g.get('score_scale'), g)
        if scale and all(scale['lower_bound'] <= s['value_numeric'] <= scale['upper_bound'] for s in g['scores']):
            ref.update(contrast_scale=(scale['upper_bound']-scale['lower_bound'])/4,
                       contrast_method='VERIFIED_QUARTER_RANGE', scale_id=scale['scale_id'])
        elif candidates := [(gid, v) for gid, v in peers[identity(g)] if gid != g['group_id']]:
            ref.update(contrast_scale=median(v for _, v in candidates),
                       contrast_method='SAME_SOURCE_PEER_SD', scale_source_groups=[gid for gid, _ in candidates])
        else:
            ref.update(contrast_scale=None, contrast_method='TWO_MODEL_ORDINAL_ONLY', information_weight=.5)
        sign = 1 if g['direction'] == 'higher' else -1
        for s in g['scores']:
            ys=[]
            for t in g['scores']:
                if s is t: continue
                d=sign*(s['value_numeric']-t['value_numeric'])
                unit=ref['contrast_scale']
                ys.append((.5 if d==0 else .75 if d>0 else .25) if unit is None
                          else 1/(1+math.exp(max(-700,min(700,-d/unit)))) if unit else .5)
            s['comparison_target']=fmean(ys)
