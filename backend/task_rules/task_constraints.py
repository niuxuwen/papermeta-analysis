"""Literal task requirements: never infer input support or source protocols."""
import re
from copy import deepcopy

MEDIA = {'text', 'image', 'audio', 'video'}
MEDIA_WORDS = {
    'image': r'截图|图像|图片|图文|影像|X[光射线]|x[ -]?ray|images?|screenshots?|photographs?',
    'audio': r'音频|录音|语音|audio|speech|music recording',
    'video': r'视频|录像|录屏|video|screen recording',
}

def required_media(value):
    if value in {'any', 'multimodal'}: return set()
    return set(value.split('+'))

def valid_modality(value):
    return isinstance(value,str) and (value in {'any','multimodal'} or
        bool(required_media(value)) and required_media(value)<=MEDIA and len(value.split('+'))==len(required_media(value)))

def literal_media(description):
    text=description.casefold()
    # A transcript or text description is not a request to ingest its media.
    text=re.sub(r'(?:音频|录音|视频|录像|audio|video|recording)(?:的)?(?:文字稿|转写稿|转录稿|transcript)', '文本', text)
    text=re.sub(r'(?:图片|图像|视频|音频)(?:的)?(?:文字描述|文本描述)', '文本', text)
    text=re.sub(r'(?:不使用|不用|无需|不需要|禁止|不能)(?:使用|用)?(?:任何)?(?:图片|图像|截图|音频|录音|视频|录像|录屏)', '', text)
    text=re.sub(r'\b(?:no|without|do not use)\s+(?:images?|audio|video)\b','',text)
    if re.search(r'纯文本|仅文本|text[ -]only',text):return 'text'
    found=[]
    for mode,words in MEDIA_WORDS.items():
        for match in re.finditer(words,text,re.I):
            before=text[max(0,match.start()-24):match.start()]
            after=text[match.end():match.end()+10]
            # Generation-only outputs do not require the same input modality.
            if re.search(r'(?:生成|绘制|画出|输出|合成|generate|create|produce)\s*(?:一[张段个]|an?\s+)?$',before) and not re.search(r'输入|input',after):continue
            found.append(mode);break
    return '+'.join(sorted(found)) if found else ('multimodal' if re.search(r'多模态|multimodal|meeting recording',text) else None)

def literal_access(description):
    text=description.casefold()
    if re.search(r'不(?:允许|能|使用|需要|用|要)?(?:联网|检索)|无需(?:联网|检索)|禁止(?:联网|检索)|closed[ -]book|without retrieval|no retrieval|offline|(?:do not|don.t) (?:browse|search) (?:the )?web',text):return 'closed_book'
    if re.search(r'联网(?:检索|搜索|查找|查询)?|(?:允许|可以|使用|需要|必须)(?:外部)?检索|网络搜索|web search|search (?:the )?web|browse (?:the )?web|with retrieval|retrieval allowed|\brag\b',text):return 'retrieval'
    if not re.search(r'不(?:允许|能|使用)?(?:使用)?工具|禁止(?:使用)?工具|no tools|without tools',text) and re.search(r'(?:允许|可以|需要|必须)?使用工具|允许工具|tool use|tools allowed',text):return 'tools'
    return None

def literal_context(description,*,input_context_only=False):
    for m in re.finditer(r'(?<![\d.])([\d,]+(?:\.\d+)?)(万|[kKmM])?\s*(?:tokens?|令牌)(?![a-z])',description):
        if re.search(r'不需要|无需|不用',description[max(0,m.start()-5):m.start()]):continue
        if input_context_only and re.search(r'输出.{0,10}$|生成.{0,10}$|(?:output|generate).{0,12}$',description[max(0,m.start()-18):m.start()],re.I):continue
        if input_context_only and not re.search(r'读|输入|上下文|材料|context|read|input|文档',description[max(0,m.start()-35):m.end()+18],re.I):continue
        factor={'万':10000,'k':1000,'m':1000000}.get((m[2]or'').lower(),1)
        n=float(m[1].replace(',',''))*factor
        if n>0 and n.is_integer():return int(n)
    return None

def normalize_generated_constraints(description,constraints,evidence):
    """Only generated profiles pass here. Manual edits remain user-controlled."""
    c,e=deepcopy(constraints),deepcopy(evidence)
    if not isinstance(c,dict) or not isinstance(e,dict):return c,e
    literal={'modality':literal_media(description),'knowledge_access':literal_access(description),
             'min_context_tokens':literal_context(description,input_context_only=True)}
    for key,value in literal.items():
        if value is not None:
            c[key]=value;e[key]=description
        else:
            # No model-added closed-book, media or token restriction.
            c[key]=None if key=='min_context_tokens' else 'any';e.pop(key,None)
    return c,e

def unverified_protocol_fields(constraints):
    # Catalogue capabilities/modalities do not certify language, tool access,
    # or context lengths. Keep these sources in an explicit reference tier.
    return [k for k in ('language','knowledge_access','min_context_tokens') if constraints[k] not in ('any',None)]
