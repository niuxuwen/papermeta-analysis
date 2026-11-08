from __future__ import annotations

import re

import unicodedata

POLICY = 'source-measurement-semantics-v4'

def rater_aggregation_diagnostic(metric, context=''):
    """Recognize a source-declared sensitivity check, not a model-name prior.

    Min/mean/max alone establishes neither a failure objective nor a diagnostic.
    Require the caption to identify pooled displacement rates and explicitly
    describe checking the effect of the rater-aggregation choice.
    """
    label = unicodedata.normalize('NFKC', str(metric)).strip()
    ctx = ' '.join(unicodedata.normalize('NFKC', str(context)).split()).casefold()
    if (re.fullmatch(r'(?i)(?:min|mean|max)\s*(?:≥|>=)\s*2\s*[%↑↓]?', label)
            and 'pooled displacement rates' in ctx
            and 'rater aggregations' in ctx
            and 'rater-aggregation choice' in ctx):
        return {'role': 'STATISTIC', 'direction': 'lower',
                'basis': 'SOURCE_DECLARED_FAILURE_RATE_RATER_AGGREGATION_SENSITIVITY',
                'quote': str(context)}
    return None

def contrast_role(metric, context=''):
    if annotation := rater_aggregation_diagnostic(metric, context):
        return annotation['role']
    label=unicodedata.normalize('NFKC',str(metric)).strip()
    ctx=unicodedata.normalize('NFKC',str(context)).replace('−','-')
    # Color difference is a final error objective, despite the delta glyph.
    if re.fullmatch(r'(?i)(?:[Δ∆]|delta)\s*E(?:\s*00|\s*2000)?\s*[↓↑]?',label) and re.search(r'(?i)\b(?:colou?r|CIEDE2000|colorimetric)\b',ctx):
        return None
    change_label=bool(re.search(r'[Δ∆]|\\[Dd]elta|(?i:\b(?:delta|gain|improvement|lift|difference|change)\b)',label))
    if not change_label:
        return None
    if (re.search(r'(?i)\b(?:inference settings?|non[- ]thinking|thinking modes?)\b', ctx)
            and re.search(r'(?i)\b(?:gain|improvement|delta)\s+is\s+(?:its|the)\s+difference\s+from\b', ctx)):
        return 'INTERVENTION_EFFECT'
    if re.search(r'(?i)\b(?:minus|margin over|relative to|gain per|effect per model)\b',ctx):
        return 'INTERVENTION_EFFECT'
    conditions=bool(re.search(r'(?i)\b(?:prompt(?:ing)?|implicit|explicit|intervention|treatment|ablation|augmentation|baseline|mitigation|fine[- ]?tun\w*|condition)s?\b',ctx+' '+label))
    definition=bool(re.search(r'(?i)\b(?:change|difference|improvement|gain)s?\s+(?:from|between|relative\s+to|over)\b|(?:[Δ∆]|\\Delta|\bdelta\b)\s*=|\b(?:relative\s+to|over|against)\s+(?:the\s+)?baseline\b|\bwith(?:out)?\b.{0,80}\bvs\.?\b',ctx+' '+label))
    if conditions and definition:
        return 'INTERVENTION_EFFECT'
    if re.search(r'(?i)\b(?:paired\s+model\s+comparisons?|differences?\s+between\s+models?|effect\s+sizes?)\b',ctx):
        return 'DERIVED_STATISTIC'
    return None

def measurement_kind(role):
    return {'PERFORMANCE':'FINAL_TASK_PERFORMANCE','INTERVENTION_EFFECT':'INTERVENTION_EFFECT',
        'STATISTIC':'STATISTICAL_DIAGNOSTIC','DERIVED_STATISTIC':'STATISTICAL_DIAGNOSTIC',
        'EFFICIENCY':'RESOURCE_MEASUREMENT','METADATA':'METADATA',
        'RELATIONAL_OR_DAMAGED_AXIS':'UNRESOLVED_AXIS','TARGET_MODEL_DIAGNOSTIC':'STATISTICAL_DIAGNOSTIC'}.get(role,'UNRESOLVED_AXIS')

def describe_group(group):
    from .source_comparison_context import resolved_role
    if annotation := rater_aggregation_diagnostic(group['metric'], group.get('metric_role_context', '')):
        group.setdefault('extracted_direction', group.get('direction'))
        group['direction'] = annotation['direction']
        group['source_measurement_annotation'] = annotation
    role=resolved_role(group)
    group.update(metric_role=role,measurement_kind=measurement_kind(role),measurement_policy=POLICY)
    return group
