from __future__ import annotations

MEDIA = {'text', 'image', 'audio', 'video'}

def required_media(value):
    if value in {'any', 'multimodal'}: return set()
    return set(value.split('+'))

def valid_modality(value):
    return isinstance(value,str) and (value in {'any','multimodal'} or
        bool(required_media(value)) and required_media(value)<=MEDIA and len(value.split('+'))==len(required_media(value)))

def unverified_protocol_fields(constraints):
    # Catalogue capabilities/modalities do not certify language, tool access,
    # or context lengths. Keep these sources in an explicit reference tier.
    return [k for k in ('language','knowledge_access','min_context_tokens') if constraints[k] not in ('any',None)]
