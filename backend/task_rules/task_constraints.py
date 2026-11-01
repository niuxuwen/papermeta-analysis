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

def _clauses(text):
    return [c for c in re.split(r'[，,。；;！!？?\n]+',text.casefold()) if c.strip()]

def _output_mention(before,after):
    # Keep the role local to this mention, not a keyword elsewhere in the task.
    output=r'输出|生成|合成|绘制|画出|返回|output|generate|produce|create|render|return'
    if re.search(r'(?:作为|用作)?输入|as (?:an? )?input',after[:16]):return False
    if re.search(r'(?:根据|读取|查看|分析|识别).{0,16}生成的\s*$',before):return False
    inputs=list(re.finditer(r'输入|读取|查看|阅读|处理|识别|分析|解读|read|input|watch|analy[sz]',before))
    outputs=list(re.finditer(output,before))
    if inputs and (not outputs or inputs[-1].start()>outputs[-1].start()):return False
    return bool(re.search(r'(?:'+output+r')[^。；;，,]{0,14}$',before)
                or re.match(r'\s*(?:形式|格式|的结果|结果)?\s*(?:输出|output)',after))

def literal_media(description):
    text=description.casefold()
    # Written surrogates are inputs in their own right, not their original media.
    media=r'录音|音频|语音|视频|录像|图片|图像|audio|video|recording|image'
    surrogate=r'逐字稿|文字稿|转写稿|转录稿|文字描述|文本描述|transcript(?:ion)?'
    text=re.sub(r'(?:'+media+r')(?:的|\s+)?(?:'+surrogate+r')','文本',text)
    text=re.sub(r'(?:'+surrogate+r')\s+of\s+(?:the\s+)?(?:'+media+r')','text',text)
    found=set();text_input=False
    for clause in _clauses(text):
        for match in re.finditer(r'纯文本|仅文本|只(?:用|接受|处理)(?:输入)?文本|text[ -]only',clause):
            if not _output_mention(clause[:match.start()],clause[match.end():]):text_input=True
        for mode,words in MEDIA_WORDS.items():
            for match in re.finditer(words,clause,re.I):
                before=clause[:match.start()];after=clause[match.end():]
                neg=r'(?:不(?:需要|允许|能|要|用|会)?|无需|无须|禁止|没有)(?:处理|提供|接收|分析|上传|使用|输入|支持|用)?(?:任何|原始|的|这些)?\s*$'
                if re.search(neg,before) or re.search(r'\b(?:no|without|do not use|do not provide)\s*(?:any\s+)?$',before):continue
                if _output_mention(before,after):continue
                found.add(mode)
    if found:return '+'.join(sorted(found))
    if text_input:return 'text'
    return 'multimodal' if re.search(r'多模态输入|multimodal input|meeting recording',text) else None

def literal_access(description):
    text=description.casefold()
    # A local retrieval requirement is compatible with a ban on web access.
    if any(re.search(r'(?:本地|离线|给定文档库).{0,12}(?:检索|搜索)|(?:检索|搜索).{0,8}(?:本地|离线)资料',c) and not re.search(r'不允许|禁止|无需|不需要',c)for c in _clauses(text)):return 'retrieval'
    if re.search(r'不(?:允许|能|使用|需要|用|要)?(?:联网|检索)|无需(?:联网|检索)|禁止(?:联网|检索)|closed[ -]book|without retrieval|no retrieval|offline|(?:do not|don.t) (?:browse|search) (?:the )?web',text):return 'closed_book'
    if re.search(r'联网(?:检索|搜索|查找|查询)?|(?:允许|可以|使用|需要|必须)(?:外部)?检索|(?:使用|通过)(?:浏览器|搜索引擎).{0,6}(?:检索|搜索|查找|查询)|网络搜索|web search|search (?:the )?web|browse (?:the )?web|with retrieval|retrieval allowed|\brag\b',text):return 'retrieval'
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
