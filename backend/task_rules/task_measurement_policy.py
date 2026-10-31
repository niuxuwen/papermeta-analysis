"""Shared final-outcome roles and audited modality matching; raw cells stay exact."""
import re
import unicodedata

POLICY = 'shared-source-roles-and-modalities-v3'

def modality_matches(requested, modalities):
    tags = set(modalities or [])
    if requested == 'any':
        return True
    if requested == 'multimodal':
        return bool(tags & {'image', 'audio', 'video'})
    return set(requested.split('+')) <= tags

def task_metric_role(group):
    from .source_comparison_context import resolved_role
    role = resolved_role(group)
    if role != 'PERFORMANCE':
        return role
    label = unicodedata.normalize('NFKC', str(group.get('metric') or ''))
    context = ' '.join(str(group.get('metric_role_context') or '').split()).casefold()
    plain = re.sub(r'[^a-z0-9]', '', label.casefold())
    if plain in {'rank','avgrank','averagerank','meanrank'} and re.search(r'ordered by (?:the )?mean|equal displayed scores share a rank|average (?:of )?.*ranks|average ranks',context):
        return 'DERIVED_RANK'
    if re.fullmatch(r'(?:ece|expectedcalibrationerror|brier(?:raw|score)?)(?:percent)?', plain):
        return 'CALIBRATION_DIAGNOSTIC'
    if (plain in {'increase', 'decrease', 'unchanged'}
            and re.search(r'task reformulation|dq.change groups|(?:elaborated|broad) versus focused', context)):
        return 'INTERVENTION_EFFECT'
    change = bool(re.search(r'[Δ∆]|\\[Dd]elta|(?i:\b(?:delta|gain|improvement|lift)\b)', label))
    if change:
        # A caption-defined action-prediction target is a physical displacement,
        # not an improvement from a prompt or intervention.
        if (re.search(r'per.step prediction performance|action prediction',context)
                and re.search(r'mean absolute error|pearson correlation',context)
                and re.search(r'(?i)(?:[Δ∆]|\\delta)\s*(?:x|y|z|ψ|theta)',label)
                and re.search(r'(?i)\b(?:mae|rmse|pearson)\b',label)):
            return 'PERFORMANCE'
        # Color error is an absolute outcome with a conventional delta symbol.
        if re.fullmatch(r'(?i)(?:[Δ∆]|delta)\s*E(?:\s*00|\s*2000)?\s*[↓↑]?', label.strip()) and re.search(r'colou?r|ciede2000|colorimetric', context):
            return 'PERFORMANCE'
        if re.search(r'(?:clean\s*[-−]\s*perturbed)|(?:denotes|defined as|difference).{0,60}(?:perturb|baseline|prompt|condition)', context):
            return 'INTERVENTION_EFFECT'
        # An undefined difference cannot establish an absolute task outcome.
        return 'UNRESOLVED_CONTRAST'
    return role
