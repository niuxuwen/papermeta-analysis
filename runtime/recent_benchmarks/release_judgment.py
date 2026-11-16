"""Read-only benchmark judgment queries; unknown and ambiguous are not old."""
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import re
import unicodedata
from urllib.parse import urlsplit

from .benchmark_dates import date_assessment


def normalize_query(value):
    if not isinstance(value,str) or not value.strip() or len(value)>512:
        raise ValueError('query must be a nonempty string of at most 512 characters')
    result=re.sub(r'\s+',' ',unicodedata.normalize('NFKC',value).strip().lower())
    match=re.fullmatch(r'https://(?:www\.)?arxiv\.org/(?:abs|html|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?',result)
    return match.group(1) if match else result


def bucket(value):
    return sha256(value.encode()).hexdigest()[:2]


def judgment(record, period):
    status=record['status'];dates=date_assessment(record);day=dates['benchmark_first_public_date']
    if status=='NOT_A_BENCHMARK': verdict,is_new='NOT_A_BENCHMARK',False
    elif day:
        is_new=period['start']<=day<period['end_exclusive']
        verdict='NEW_IN_PERIOD' if is_new else 'EXISTING_OR_OUTSIDE_PERIOD'
    elif status=='EXISTING_OR_UPDATE':verdict,is_new='EXISTING_OR_UPDATE',False
    else:verdict,is_new='PENDING',None
    return {'entity_id':record['entity_id'],'name':record['name'],
        'kind':record.get('kind','UNKNOWN'),'scope':record.get('scope','UNVERIFIED'),
        'judgment':verdict,'is_new_in_report_period':is_new,'report_period':period,
        'identity_status':status,**dates,
        'identity_evidence':deepcopy(record.get('identity_evidence')),
        'firstness_evidence':deepcopy(record.get('firstness_evidence')),
        'source_refs':[{k:r.get(k) for k in ('paper_id','benchmark_id','benchmark_name','arxiv_id',
            'paper_first_published','source_url','release_date','date_basis')} for r in record.get('source_records',[])],
        'needs_research':is_new is None,
        'reasons':record.get('reasons',[]) or (['REVIEW_INCOMPLETE'] if is_new is None else []),
    }


def lookup_keys(record):
    keys={record['entity_id'],record['name']}
    aliases=record.get('aliases',[])
    if isinstance(aliases,list):keys.update(a for a in aliases if isinstance(a,str))
    for ref in record.get('source_records',[]):
        if ref.get('paper_id') and ref.get('benchmark_id'):
            keys.add(ref['paper_id']+'::'+ref['benchmark_id'])
        keys.update(ref.get(k) for k in ('benchmark_name','benchmark_id','paper_id','arxiv_id','source_url'))
        aliases=ref.get('benchmark_aliases',[])
        if isinstance(aliases,list):keys.update(a for a in aliases if isinstance(a,str))
    for e in record.get('events',[]):
        url=(e.get('evidence') or {}).get('url')
        if url:
            keys.add(url)
            u=urlsplit(url)
            if u.hostname in {'github.com','raw.githubusercontent.com'}:
                parts=u.path.strip('/').split('/')
                if len(parts)>=2:keys.add('https://github.com/'+'/'.join(parts[:2]))
    return {normalize_query(k) for k in keys if isinstance(k,str) and k.strip() and len(k)<=512}


def query_index(records):
    index=defaultdict(set)
    for r in records:
        for key in lookup_keys(r):index[key].add(r['entity_id'])
    return {k:sorted(v) for k,v in sorted(index.items())}


def answer(query, judgments, index, *, metadata=None, paper_id=None, limit=50):
    key=normalize_query(query)
    ids=index.get(key,[])
    rows=[judgments[i] for i in ids if i in judgments]
    if paper_id:
        rows=[r for r in rows if any(x.get('paper_id')==paper_id for x in r['source_refs'])]
    count=len(rows)
    status='NOT_FOUND' if not count else 'MATCHED' if count==1 else 'AMBIGUOUS'
    return {**(metadata or {}),'query':query,'normalized_query':key,'result_status':status,
        'judgment':rows[0]['judgment'] if count==1 else 'PENDING',
        'is_new_in_report_period':rows[0]['is_new_in_report_period'] if count==1 else None,
        'needs_research':not count or count!=1 or rows[0]['needs_research'],
        'match_count':count,'matches':deepcopy(rows[:limit]),'truncated':count>limit,
        'reason':'NO_VERIFIED_IDENTITY_MATCH' if not count else
                 'SELECT_AN_EXACT_ENTITY_OR_PAPER' if count>1 else None,
        'notice':'未命中或待核不代表旧benchmark；本接口查询已保存证据，不自动把提交日期当首发。'}
