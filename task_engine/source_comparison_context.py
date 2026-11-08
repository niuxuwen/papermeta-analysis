from __future__ import annotations

import re

def normalized(value):
    return ' '.join(str(value or '').split()).casefold()

def source_role(group, benchmark):
    """A caption alone is insufficient to establish a model-as-target axis."""
    ctx = normalized(group.get('metric_role_context'))
    quote = normalized(benchmark.get('evidence_quote'))
    exact_binding = (group.get('paper_id'), group.get('benchmark_id')) == (
        benchmark.get('paper_id'), benchmark.get('benchmark_id'))
    if (exact_binding and ctx and ctx in quote
            and re.search(r'\bunderlying model\s*\|', quote)
            and re.search(r'\battribution performance\b.*\bidentity spoofing\b', ctx)):
        return {'role': 'TARGET_MODEL_DIAGNOSTIC', 'basis': 'EXACT_CAPTION_AND_UNDERLYING_MODEL_AXIS',
                'quote': benchmark['evidence_quote'], 'caption': group['metric_role_context']}
    label = normalized(group.get('metric')).rstrip('↑↓').strip()
    if (re.fullmatch(r'(?:gain|improvement|delta)', label)
            and re.search(r'\b(?:inference settings?|non[- ]thinking|thinking modes?)\b', ctx)
            and re.search(r'\b' + re.escape(label) + r'\s+is\s+(?:its|the)\s+difference\s+from\b', ctx)):
        return {'role': 'INTERVENTION_EFFECT', 'basis': 'EXPLICIT_CONDITION_DIFFERENCE_DEFINITION',
                'quote': group['metric_role_context']}
    return None

def resolved_role(group):
    """Recheck transported source-role proofs before trusting their role."""
    from .publication_quality import metric_role
    proof = group.get('source_role_annotation') or {}
    if all(proof.get(k) == group.get(k) for k in ('paper_id', 'benchmark_id', 'table_id', 'metric')):
        benchmark = {'paper_id': group.get('paper_id'), 'benchmark_id': group.get('benchmark_id'),
                     'evidence_quote': proof.get('quote', '')}
        checked = source_role(group, benchmark)
        if checked and checked['role'] == proof.get('role'):
            return checked['role']
    return metric_role(group['metric'], group.get('metric_role_context', ''))

def global_condition_exclusion(group):
    """Explicit secondary inference settings remain source results, not defaults."""
    condition = group.get('source_inference_condition') or {}
    if condition.get('status') != 'SETTING_REPORTED_ON_METRIC_AXIS':
        return None
    label = normalized(condition.get('source_label'))
    if label in {'cot', 'zs+d', 'tree', 'tree+d', 'non-thinking'}:
        return 'explicit_secondary_inference_condition'
    return None
