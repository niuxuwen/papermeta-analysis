"""Narrow validation for reused, audited historical public-by receipts."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    raw=Path(__file__).with_name('audited_date_facts.json').read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def fact_evidence(fact):
    data,sha=catalog()
    return {'evidence_type':'AUDITED_PUBLIC_BY_FACT_RECEIPT','primary':True,
        'review_status':'VERIFIED','url':fact['source_url'],'reviewed_at':fact['checked_on']+'T00:00:00Z',
        'summary':fact['name']+'：复用已审核主来源的公开时间上界；不是首发日期，也不是本轮重新阅读历史论文。',
        'fact_receipt':{'catalog_sha256':sha,'revision':data['revision'],'fact':fact}}


def valid_fact_evidence(value):
    if not isinstance(value,dict) or value.get('evidence_type')!='AUDITED_PUBLIC_BY_FACT_RECEIPT':return False
    data,sha=catalog();r=value.get('fact_receipt') or {}
    return (r.get('catalog_sha256')==sha and r.get('revision')==data['revision']
        and r.get('fact') in data['facts'] and value.get('url')==r['fact']['source_url']
        and value.get('primary') is True and value.get('review_status')=='VERIFIED'
        and bool(value.get('summary')))
