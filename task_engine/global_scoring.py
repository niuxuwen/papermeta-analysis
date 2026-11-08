from __future__ import annotations

from collections import Counter, defaultdict

import math

from statistics import fmean, pstdev

from .paired_scoring import sigmoid

from .scoring_preparation import digest

from .publication_quality import general_model_issue

from .measurement_semantics import describe_group

from .source_comparison_context import global_condition_exclusion

POLICY = 'vendor-blind-source-calibrated-composite-v16'

MARGIN_TEMPERATURE = 1.0

def comparison_target(group, first, second):
    """Continuous, dimensionless same-condition contrast, not an item vote.

    This is an empirical relative scale, not a verified 0--100 source range or
    a significance test. With only two references its magnitude is necessarily
    uninformative about absolute practical importance.
    """
    ref=group['reference_profile']
    if ref.get('contrast_method')=='TWO_MODEL_ORDINAL_ONLY':
        delta=(first['value_numeric']-second['value_numeric'])*(1 if group['direction']=='higher' else -1)
        return .5 if delta==0 else .75 if delta>0 else .25
    sd=ref.get('contrast_scale',ref['standard_deviation'])
    if not sd:
        return .5
    a,b=first['value_numeric'],second['value_numeric']
    scale=max(abs(a),abs(b),sd) or 1.0
    delta=((a/scale)-(b/scale))/(sd/scale)
    return sigmoid((1 if group['direction']=='higher' else -1)*delta/MARGIN_TEMPERATURE)

def prepare_contests(index, *, scope='global'):
    counts,by_setting = Counter(),defaultdict(list)
    for g in index['groups']:
        g.pop('reference_profile',None)
        g.pop('global_pair_weights',None)
        g['global_reference_models'] = []
        g['global_pair_weight'] = None
        g['global_status'] = 'OUTSIDE_BROAD_COVERAGE_CORE'
        for s in g['scores']:
            s.pop('relative_score',None)
            s.pop('pairwise_score',None)
            s.pop('comparison_target',None)
        reason = None
        describe_group(g)
        from .task_measurement_policy import task_metric_role
        g['metric_role']=task_metric_role(g)
        if g['metric_role'] != 'PERFORMANCE':
            reason = 'non_capability_metric:' + g['metric_role']
        elif scope=='global' and global_condition_exclusion(g):
            reason = global_condition_exclusion(g)
        elif g.get('blocked_reasons') or g.get('extraction_in_progress'):
            reason = 'blocked_or_incomplete_source_group'
        elif len([s for s in g['scores'] if not general_model_issue(s['model_canonical'])])<2:
            reason = 'insufficient_reference_models'
        elif g.get('direction') not in ('higher','lower'):
            reason = 'unknown_direction'
        else:
            ordered = sorted((s for s in g['scores'] if not general_model_issue(s['model_canonical'])),key=lambda s:s['model_canonical'])
            values = [s['value_numeric'] for s in ordered]
            if not all(math.isfinite(v) for v in values):
                reason = 'nonfinite_source_values'
            else:
                scale = max(map(abs,values)) or 1.0
                reduced = [v/scale for v in values]
                reduced_mean,reduced_sd = fmean(reduced),pstdev(reduced)
                mean,sd = reduced_mean*scale,reduced_sd*scale
                ref = digest([POLICY,g['group_id'],[(s['model_canonical'],s['value_numeric'],s.get('observation_ids',[])) for s in ordered]])[:24]
                g['reference_profile'] = dict(policy=POLICY,reference_id=ref,reference_count=len(values),mean=mean,
                    reference_models=[s['model_canonical'] for s in ordered],
                    standard_deviation=sd,ddof=0,direction=g['direction'],records_fingerprint=g.get('records_fingerprint'))
                sign = 1 if g['direction']=='higher' else -1
                for s in ordered:
                    s['relative_score'] = sign*(s['value_numeric']/scale-reduced_mean)/reduced_sd if reduced_sd else 0
                    outcomes = [1 if sign*(s['value_numeric']-t['value_numeric'])>0 else .5 if s['value_numeric']==t['value_numeric'] else 0
                                for t in ordered if t['model_canonical']!=s['model_canonical']]
                    s['pairwise_score'] = 100*fmean(outcomes)
                    s['comparison_target'] = fmean(comparison_target(g,s,t) for t in ordered if t is not s)
                by_setting[g['model_setting']].append(g)
        g['relative_status'] = reason or 'READY'
        counts[g['relative_status']] += 1
    from .task_balanced_scoring import prepare_contrast_scales
    for groups in by_setting.values(): prepare_contrast_scales(groups)
    return by_setting,dict(counts)
