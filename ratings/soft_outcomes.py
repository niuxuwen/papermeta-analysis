"""Source-score soft outcomes; fit once, reuse identical observations in all boards.

Implements the PDF's three observation links, not its table exclusion policy.
Empirical RMS is a scale convention, not an estimated sampling standard error.
"""
import math
import re
from collections import defaultdict
from itertools import combinations

METHOD = 'source-gap-soft-outcome-v1'
EPS = 1e-12  # numerical guard only, not an evidence threshold


def scale_key(group):
    return (group.get('benchmark_identity') or group['benchmark_id'],
            ' '.join(group['metric'].split()), group['direction'])


def rms_scales(prepared):
    sums = defaultdict(lambda: [0., 0])
    seen = set()
    for group, scores in prepared:
        key = scale_key(group)
        # Same source cells exported twice must not alter the scale.
        signature = (key, group['paper_id'], group.get('table_id'),
                     group.get('source_condition_key', group.get('model_setting', '')),
                     tuple(sorted((s['model_canonical'], s.get('dedup_condition', ''),
                                   s['value_numeric']) for s in scores)))
        if signature in seen:
            continue
        seen.add(signature)
        for a, b in combinations(scores, 2):
            delta = a['value_numeric'] - b['value_numeric']
            sums[key][0] += delta * delta
            sums[key][1] += 1
    return {key: math.sqrt(total / count) for key, (total, count) in sums.items() if count}


def binomial_spec(group):
    """Only reviewed evaluated-subset n and explicit binary accuracy units.

    A dataset total, F1, pass@k estimate, averaged rubric, or raw percentage is
    insufficient. Unclassified metrics remain usable through the empirical link.
    """
    proof = group.get('sample_size') or {}
    n = group.get('evaluation_n')
    if (proof.get('status') != 'SOURCE_REVIEWED' or proof.get('scope') != 'evaluated_subset'
            or isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n)
            or n <= 0 or int(n) != n or proof.get('n') != n):
        return None
    metric = group['metric'].casefold()
    if not re.search(r'\baccuracy\b', metric) or any(x in metric for x in ('balanced', 'macro', 'weighted', 'average')):
        return None
    # No inference from value magnitude: 0.8 might mean 0.8% or 80%.
    if '%' not in metric:
        return None
    return n, 100.


def outcome(group, a, b, scales):
    sign = 1 if group['direction'] == 'higher' else -1
    delta = (a['value_numeric'] - b['value_numeric']) * sign
    detail = dict(method='empirical_rms', delta=delta, n=None)
    metric = group['metric'].casefold()
    if re.fullmatch(r'(?:arena\s+)?elo(?:\s+(?:rating|score))?(?:\s*[↑↓])?', metric.strip()):
        z = delta * math.log(10) / 400
        e = math.exp(-abs(z))
        y = 1 / (1 + e) if z >= 0 else e / (1 + e)
        detail.update(method='arena_elo', scale=400.)
    else:
        spec = binomial_spec(group)
        if spec:
            n, unit = spec
            pa, pb = a['value_numeric'] / unit, b['value_numeric'] / unit
            if not (0 <= pa <= 1 and 0 <= pb <= 1):
                spec = None
        if spec:
            # Run noise must be explicitly recorded in score units; no parsing
            # of arbitrary ± annotations as SE. Unreported noise assumed zero.
            ra, rb = a.get('run_noise_sd', 0.), b.get('run_noise_sd', 0.)
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in (ra, rb)):
                raise ValueError('Invalid reported run noise')
            scale = math.sqrt(pa * (1-pa) / n + pb * (1-pb) / n
                              + (ra / unit)**2 + (rb / unit)**2)
            delta = (pa - pb) * sign
            detail.update(method='binomial_independent_approximation', delta=delta,
                          scale=scale, n=n, unreported_run_noise_assumed_zero=('run_noise_sd' not in a or 'run_noise_sd' not in b))
        else:
            scale = scales[scale_key(group)]
            detail['scale'] = scale
        y = (.5 if delta == 0 else (1. if delta > 0 else 0.)) if scale == 0 else .5 * math.erfc(-delta / scale / math.sqrt(2))
    return min(1-EPS, max(EPS, y)), detail
