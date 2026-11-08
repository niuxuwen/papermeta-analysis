from __future__ import annotations

from copy import deepcopy

import math

from numbers import Real

VERSION = 'score-scale-v1'

def finite(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False

def validate_scale(scale, group):
    """The caller approves source interpretation; verify its bound provenance here."""
    if not isinstance(scale, dict):
        return None, 'missing_verified_score_scale'
    if (scale.get('schema_version') != VERSION or scale.get('status') != 'APPROVED'
            or scale.get('evidence_verified') is not True):
        return None, 'unapproved_score_scale'
    for field in ('scale_id', 'unit', 'protocol_id', 'benchmark_version', 'paper_id', 'table_id', 'metric'):
        if not isinstance(scale.get(field), str) or not scale[field].strip():
            return None, 'incomplete_score_scale'
    if any(scale.get(field) != group.get(field) for field in ('paper_id', 'table_id', 'metric')):
        return None, 'score_scale_source_mismatch'
    if scale.get('direction') != group.get('direction'):
        return None, 'score_scale_direction_mismatch'
    if scale.get('direction') not in {'higher', 'lower'}:
        return None, 'score_scale_direction_mismatch'
    lo, hi = scale.get('lower_bound'), scale.get('upper_bound')
    if not finite(lo) or not finite(hi) or not lo < hi or not finite(hi - lo):
        return None, 'invalid_score_scale_bounds'
    evidence = scale.get('evidence')
    if (not isinstance(evidence, dict) or evidence.get('source_id') != group.get('table_id')
            or not isinstance(evidence.get('quote'), str) or not evidence['quote'].strip()
            or not isinstance(evidence.get('source_text'), str)
            or evidence['quote'] not in evidence['source_text']):
        return None, 'unverified_score_scale_quote'
    baseline = scale.get('chance_baseline')
    if baseline is not None and (scale['direction'] != 'higher' or not finite(baseline) or not lo <= baseline < hi):
        return None, 'invalid_chance_baseline'
    return deepcopy(scale), None
