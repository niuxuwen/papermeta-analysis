from __future__ import annotations

from functools import lru_cache

import re

import unicodedata

def text(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').split())

def identity_issue(name):
    value = text(name)
    checkpoint = re.sub(r'(?i)\s*\((?:none|minimal|low|medium|high|xhigh|max|thinking|non-thinking)\)$', '', value)
    if not value:
        return 'NON_MODEL_LABEL'
    if re.fullmatch(r'(?i)(?:ours?|our model|our method|baseline|base|random|human|teacher|student|'
                    r'one shot|zero shot|\d+[- ]shot|model\s*\d+|[+\-]|\d+(?:\.\d+)?\s*[%\\]*)'
                    r'(?:\s*\([^)]*\)|\s+w/o\b.*)?', value):
        return 'SOURCE_LOCAL_LABEL'
    if re.fullmatch(r'(?i)(?:sol|luna|terra|astra|gpt[- ](?:sol|luna|terra|astra))', value):
        return 'UNRESOLVED_MODEL_IDENTITY'
    if re.fullmatch(r'(?i)(?:Gemini|Qwen|Llama)\s+\d+(?:\.\d+)*', checkpoint):
        return 'UNSPECIFIED_VERSION'
    if re.fullmatch(r'(?i)Qwen\s+\d+(?:\.\d+)*\s+(?:VL|Omni)(?:\s+(?:Instruct|Thinking))?', checkpoint):
        return 'UNSPECIFIED_CHECKPOINT_SIZE'
    if re.match(r'(?i)^(?:Qwen|Llama)\s+\d{2}(?=\s|$)', value):
        return 'AMBIGUOUS_VERSION_SEPARATOR'
    # A score/interval attached to a complete family label is damaged axis
    # evidence. Do not strip the number and pretend the source was validated.
    if re.match(r'(?i)^(?:claude|gemini|gpt|qwen)\b', value) and (
            re.search(r'\s\d+\.\d+\s*\(\s*\d+\s*,\s*\d+\s*\)$', value)
            or re.search(r'\s0\.\d{2,}$', value)):
        return 'MODEL_LABEL_CONTAINS_STATISTIC'
    # OCR/logos and LaTeX footnotes require the original axis, not a guessed
    # parent identity. Existing raw labels are retained outside ranking.
    if re.match(r'(?i)^(?:[$∞]|\d+\s+(?:gpt|qwen)|z\s*\|?\s*glm|q\s*hy\d|0\s+hy\d)', value):
        return 'DAMAGED_MODEL_LABEL'
    if re.search(r'\\(?:dagger|ddagger|bm)\b|[∗†‡]', value):
        return 'ANNOTATED_MODEL_LABEL'
    return None

def general_model_issue(name):
    """General-index admission, distinct from retaining a valid raw identity."""
    if issue := identity_issue(name):
        return issue
    # Meta explicitly documents this family as a safety classifier. It remains
    # a valid source model, but is not a general assistant reference opponent.
    if re.match(r'(?i)^Llama\s*Guard\b', text(name)):
        return 'SPECIALIZED_SAFETY_CLASSIFIER'
    return None

def metric_role(metric, context=''):
    value = text(metric).replace('\\uparrow', '↑').replace('\\downarrow', '↓')
    from .measurement_semantics import contrast_role
    contrast = contrast_role(value,context)
    if contrast:
        return contrast
    if re.search(r'(?i)inter[ -]?(?:annotator|rater) agreement',context):
        return 'STATISTIC'
    if re.search(r'(?i)\b(?:averages? per.metric ranks|avg\.? rank|average ranks)\b',context) and re.fullmatch(r'(?i)(?:avg\.?\s*)?rank\s*[↓↑]?',value):
        return 'DERIVED_STATISTIC'
    if re.fullmatch(r'(?i)(?:GCS|KBS)',value) and re.search(r'(?i)\b(?:calibration|knowledge boundary|diagnostic|consistency)\b',context):
        return 'STATISTIC'
    if re.fullmatch(r'(?i)(?:T|τ)90',value) and re.search(r'(?i)first round reaching',context):
        return 'EFFICIENCY'
    if re.search(r"(?i)\b(?:cohen['’]?s?\s+d|hedges['’]?s?\s+g|effect\s+size|[tzf][ -]statistic)\b", value):
        return 'DERIVED_STATISTIC'
    if re.fullmatch(r'(?i)p[ _-]?(?:Holm|Bonferroni|BH|FDR)(?:\s*\([^)]*\))?', value):
        return 'STATISTIC'
    if re.search(r'(?i)\brank\s*\[.*(?:interval|CI)', value):
        return 'DERIVED_STATISTIC'
    if re.search(r'(?i)\bbootstrap\b.*\brank|\brank\s+stability\b', context) and re.fullmatch(
            r'(?i)(?:(?:mean|average)\s+)?rank(?:\s*\[.*\])?\s*[↓↑]?|first\s*(?:\(%\)|%)?', value):
        return 'DERIVED_STATISTIC'
    # Bare P can mean precision. Only source-bound test terminology establishes
    # that it is a significance statistic; never infer this from its magnitude.
    if re.fullmatch(r'(?i)p(?:[ -]?value)?\s*[↓↑]?', value) and (
            re.search(r'(?i)\bp[ -]?value\b', value)
            or (re.search(r'(?i)\bp(?:[ -]?values?\b|\s*[<=>≤≥])', context)
                and re.search(r'(?i)\b(?:McNemar|significance|paired tests?|hypothesis test)\b', context))):
        return 'STATISTIC'
    if re.match(r'(?i)^(?:sd|s\.?d\.?|se|s\.?e\.?)(?=$|\s|\()', value) or re.search(
            r'(?i)\b(?:standard deviation|standard error|variance|confidence interval width|sample size)\b', value):
        return 'STATISTIC'
    if re.fullmatch(r'(?i)(?:n|#?\s*(?:samples?|parameters?|params?))(?:\s*\([^)]*\))?', value):
        return 'METADATA'
    # Operation/memory/energy budgets describe resource expenditure. Preserve
    # explicit error/accuracy objectives such as "Runtime Err. %" as ability
    # measurements; a resource word in a source caption alone is insufficient.
    if re.search(r'(?i)\b(?:[gmtp]?flops?|[gmtp]?macs)\b|\b(?:peak |gpu |device |allocated )?memory\s*(?:usage|footprint|\(|\[|[↓↑]|$)|\b(?:energy|power)\s*(?:consumption|usage|\(|\[|[↓↑]|$)|\bthroughput\b|\b(?:tokens?|samples?|requests?)\s*/\s*(?:s|sec|second)\b', value):
        return 'EFFICIENCY'
    if re.search(r'(?i)\bcost\b|\blatency\b|\btime\s*(?:\[|\(|[↓↑]|$)|\btokens?\b|\bturns?\b|\$/|\$\s*/|\bcalls\b|^runtime\s*(?:\(|\[|$)|\bUSD\s*/|\bsteps?\s*/\s*task\b|\bout\s+k\s*/\s*task\b', value):
        return 'EFFICIENCY'
    if re.match(r'(?i)^(?:gpt[- ]?\d|gemini[- ]?\d|qwen[- ]?\d|gemma[- ]?\d)', value) or value.casefold() == 'name':
        return 'RELATIONAL_OR_DAMAGED_AXIS'
    # A mean with a CI annotation is still a performance estimate. Neither
    # bounds nor the direction are inferred by this classifier.
    return 'PERFORMANCE'
