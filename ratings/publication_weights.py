"""User policy: paper-first-publication decay and official-source-only modifier."""
from datetime import datetime
import math

def date(value):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:raise ValueError('Date must have timezone')
    return dt

def time_factor(first_published,as_of,half_life_months=2.,days_per_month=30.4375):
    if half_life_months<=0 or days_per_month<=0:raise ValueError('Invalid decay scale')
    age_days=(date(as_of)-date(first_published)).total_seconds()/86400
    if age_days<0:raise ValueError('Future publication relative to frozen snapshot')
    return 2**(-age_days/(half_life_months*days_per_month))

def official_factor(paper,registry):
    hits=[e for e in registry['entries']if e['paper_id']==paper['paper_id']and e['arxiv_id']==paper['arxiv_id']]
    if len(hits)>1:raise ValueError('Ambiguous official source registry')
    if not hits:return registry['unconfirmed_multiplier'],{'status':'NOT_CONFIRMED_OFFICIAL','affiliation_is_not_publisher_proof':True}
    hit=hits[0]
    if not hit.get('evidence')or not hit['status'].startswith('CONFIRMED_'):raise ValueError('Official modifier requires explicit release evidence')
    return registry['confirmed_multiplier'],hit

def composite(source,time=1.,report=1.):
    if any(not math.isfinite(v)or v<=0 or v>1 for v in(source,time,report)):raise ValueError('Factors must be in (0,1]')
    return min(1.,max(.05,source*time*report))
