"""Benchmark first-publication accounting, independent of score eligibility.

Snapshots contain evaluation assets, not a census of newly released benchmarks.
Only reviewed entity/event evidence may credit a release day. Unknown dates
remain unallocated; PAPER_V1_PROXY, ingestion time and numeric scores never
establish a first-publication event.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from urllib.parse import urlsplit
from .benchmark_dates import date_assessment, first_date
from .automatic_date_policy import valid_fact_evidence

POLICY = 'benchmark-first-publication-ledger-v1'
BEIJING = timezone(timedelta(hours=8))
KINDS = {'BENCHMARK', 'METRIC', 'SUBSET', 'ABLATION', 'SUBTASK', 'MIRROR', 'UNKNOWN', 'METHOD', 'FRAMEWORK', 'MODEL'}
DECISIONS = {'CONFIRMED_NEW', 'EXISTING_OR_UPDATE', 'NOT_A_BENCHMARK', 'PENDING'}
EVENTS = {'FIRST_PUBLIC_INTRODUCTION', 'CODE_RELEASE', 'DATA_RELEASE', 'UPDATE',
          'PUBLIC_ANNOUNCEMENT', 'KNOWN_PUBLIC_EXISTENCE', 'REPOSITORY_RECORD_CREATED'}
FIRST_DATE_BASES = {'AUTHOR_DATED_ANNOUNCEMENT', 'PUBLISHER_RELEASE_TIMESTAMP',
                    'PAPER_FIRST_PUBLICATION_WITH_NEW_CLAIM'}


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def https_url(value):
    try:
        u = urlsplit(value)
        return (u.scheme == 'https' and bool(u.hostname) and not u.username
                and not u.password and not u.fragment.startswith('javascript:'))
    except (ValueError, TypeError):
        return False


def evidence(value):
    if valid_fact_evidence(value):return True
    return (isinstance(value, dict) and value.get('primary') is True
            and value.get('review_status') == 'VERIFIED'
            and https_url(value.get('url'))
            and isinstance(value.get('quote'), str) and bool(value['quote'].strip())
            and isinstance(value.get('reviewed_at'), str)
            and bool(value['reviewed_at'].strip()))


def event_day(event):
    """Date-only claims require an explicit time zone; never assume midnight."""
    value = event.get('at')
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.astimezone(BEIJING).date().isoformat(), None
        except ValueError:
            pass
        return None, 'EVENT_TIMESTAMP_NOT_TIMEZONE_AWARE'
    value = event.get('date')
    if isinstance(value, str) and event.get('timezone') in {'Asia/Shanghai', '+08:00'}:
        try:
            return date.fromisoformat(value).isoformat(), None
        except ValueError:
            return None, 'INVALID_EVENT_DATE'
    return None, 'EVENT_DATE_OR_TIMEZONE_UNVERIFIED'


def validate_registry(registry):
    if registry.get('version') != 1 or not isinstance(registry.get('entities'), list):
        raise ValueError('Unsupported release evidence registry')
    ids, bindings = set(), {}
    for row in registry['entities']:
        entity = row.get('entity_id')
        if not isinstance(entity, str) or not entity or entity in ids:
            raise ValueError('Missing or duplicate release entity_id')
        ids.add(entity)
        if not isinstance(row.get('name'), str) or not row['name'].strip():
            raise ValueError('Release entity name is required')
        if row.get('kind') not in KINDS or row.get('decision') not in DECISIONS:
            raise ValueError('Invalid release entity decision or kind')
        if row['decision'] != 'PENDING' and not evidence(row.get('identity_evidence')):
            raise ValueError('Reviewed primary identity evidence is required')
        if row['decision'] == 'CONFIRMED_NEW':
            if row['kind'] != 'BENCHMARK' or row.get('scope') != 'LLM':
                raise ValueError('Only reviewed LLM benchmark entities can count as new')
            if not evidence(row.get('firstness_evidence')):
                raise ValueError('Independent first-introduction review is required')
        if valid_fact_evidence(row.get('firstness_evidence')) or valid_fact_evidence(row.get('identity_evidence')):
            raise ValueError('Historical upper-bound receipts cannot prove identity or first introduction')
        if row['decision'] == 'NOT_A_BENCHMARK' and row['kind'] in {'BENCHMARK', 'UNKNOWN'}:
            raise ValueError('A non-benchmark disposition needs an established entity kind')
        for ref in row.get('source_refs', []):
            if not all(isinstance(ref.get(k), str) and ref[k] for k in ('paper_id', 'benchmark_id')):
                raise ValueError('Entity bindings require exact paper_id and benchmark_id')
            key = ref['paper_id'], ref['benchmark_id']
            if key in bindings and bindings[key] != entity:
                raise ValueError('One source record cannot bind to two release entities')
            bindings[key] = entity
        for event in row.get('events', []):
            if event.get('kind') not in EVENTS:
                raise ValueError('Invalid publication event kind')
            if valid_fact_evidence(event.get('evidence')) and (
                    event['kind']!='KNOWN_PUBLIC_EXISTENCE'
                    or event.get('date')!=event['evidence']['fact_receipt']['fact']['public_by']):
                raise ValueError('Historical fact receipts are restricted to the audited public-by bound')
    return bindings


def public_event(event, cutoff=None):
    day, issue = event_day(event)
    if (event.get('kind') == 'FIRST_PUBLIC_INTRODUCTION'
            and event.get('date_basis') not in FIRST_DATE_BASES):
        day, issue = None, 'FIRST_PUBLICATION_DATE_BASIS_UNVERIFIED'
    after_cutoff=False
    if cutoff is not None:
        after_cutoff=bool(day and day>cutoff.astimezone(BEIJING).date().isoformat())
        if event.get('at') and not issue:
            after_cutoff=after_cutoff or datetime.fromisoformat(event['at'].replace('Z','+00:00'))>cutoff
        if event.get('author_date_claim'):
            after_cutoff=after_cutoff or event['author_date_claim']>cutoff.astimezone(BEIJING).date().isoformat()
    return {**deepcopy(event), 'beijing_date': day, 'date_issue': issue, 'after_audit_cutoff':after_cutoff,
            'evidence_verified': evidence(event.get('evidence'))}


def source_projection(row):
    # No names/aliases are used as cross-paper identity proof.
    keys = ('paper_id', 'benchmark_id', 'benchmark_name', 'arxiv_id', 'source_url',
            'paper_first_published', 'release_date', 'date_basis', 'novelty',
            'eligibility', 'directory_identity', 'catalog_identity', 'benchmark_aliases')
    result = {k: deepcopy(row[k]) for k in keys if k in row}
    result['source_claim_quote'] = str(row.get('evidence_quote') or '')[:2000]
    return result


def build_ledger(catalog, registry, *, snapshot_id, source_sha256, source_generated_at,
                 period_start, period_end, as_of):
    """period_end is exclusive; the two-week user report includes all 14 days."""
    start, end = date.fromisoformat(period_start), date.fromisoformat(period_end)
    if not start < end or (end-start).days > 366:
        raise ValueError('Invalid release statistics period')
    cutoff = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
    if cutoff.tzinfo is None:
        raise ValueError('as_of must include a time zone')
    cutoff_day = cutoff.astimezone(BEIJING).date().isoformat()
    bindings = validate_registry(registry)
    reviewed = {r['entity_id']: r for r in registry['entities']}
    candidates = defaultdict(list)
    date_bases = Counter()
    unclassified_evaluations = 0
    seen = {}
    source_dates = []
    for source in catalog:
        if not isinstance(source, dict) or not source.get('paper_id') or not source.get('benchmark_id'):
            continue
        row = source_projection(source)
        key = row['paper_id'], row['benchmark_id']
        signature = digest(row)
        if seen.get(key) == signature:
            continue
        if key in seen:
            raise ValueError('Conflicting duplicate snapshot source record')
        seen[key] = signature
        source_dates.append({k: deepcopy(v) for k,v in row.items() if k!='source_claim_quote'})
        date_bases[str(row.get('date_basis') or 'UNKNOWN')] += 1
        entity = bindings.get(key)
        if (entity is None and row.get('novelty') not in {'NEW', 'EXISTING'}
                and row.get('date_basis') not in
                {'PAPER_V1_PROXY', 'FIRST_DISCLOSURE', 'EXPLICIT_RELEASE'}):
            # Preserve the coverage gap, not thousands of misleading "new"
            # candidates drawn from reused, undated evaluation assets.
            unclassified_evaluations += 1
            continue
        if entity is None:
            entity = 'unresolved-' + digest(list(key))[:24]
        candidates[entity].append(row)
    records = []
    for entity in sorted(set(candidates) | set(reviewed)):
        refs = candidates.get(entity, [])
        decision = reviewed.get(entity)
        if decision is None:
            record = {'entity_id': entity, 'name': refs[0].get('benchmark_name') or '名称待核',
                      'kind': 'UNKNOWN', 'decision': 'PENDING', 'scope': 'UNVERIFIED',
                      'status': 'PENDING_ENTITY_AND_FIRST_PUBLICATION',
                      'reasons': ['SOURCE_ELIGIBILITY_IS_NOT_NOVELTY', 'FIRST_PUBLIC_EVENT_UNVERIFIED'],
                      'events': [], 'first_public_date': None}
            if refs[0].get('novelty') == 'EXISTING' and refs[0]['source_claim_quote']:
                record.update(status='SOURCE_REPORTED_EXISTING', reasons=['NOT_A_NEW_RELEASE_CLAIM'])
        else:
            record = {k: deepcopy(v) for k, v in decision.items() if k != 'source_refs'}
            record['events'] = [public_event(e,cutoff=cutoff) for e in decision.get('events', [])]
            record.update(first_public_date=None, reasons=[])
            if decision['decision'] in {'EXISTING_OR_UPDATE', 'NOT_A_BENCHMARK'}:
                record['status'] = decision['decision']
                if decision['decision']=='EXISTING_OR_UPDATE':
                    day, _ = first_date(record['events'], evidence(decision.get('firstness_evidence')), cutoff)
                    record['first_public_date'] = day
            elif decision['decision'] != 'CONFIRMED_NEW':
                record.update(status='PENDING_ENTITY_AND_FIRST_PUBLICATION', reasons=['REVIEW_INCOMPLETE'])
            else:
                first = [e for e in record['events'] if e['kind'] == 'FIRST_PUBLIC_INTRODUCTION']
                days = {e['beijing_date'] for e in first if e['evidence_verified'] and not e['date_issue']}
                if not first:
                    record.update(status='PENDING_FIRST_PUBLICATION', reasons=['ARTIFACT_RELEASE_IS_NOT_FIRST_INTRODUCTION'])
                elif any(not e['evidence_verified'] or e['date_issue'] for e in first):
                    record.update(status='PENDING_FIRST_PUBLICATION', reasons=['EVENT_DATE_OR_EVIDENCE_UNVERIFIED'])
                elif len(days) != 1:
                    record.update(status='PENDING_CONFLICTING_FIRST_DATES', reasons=['CONFLICTING_FIRST_PUBLICATION_DATES'])
                elif next(iter(days)) > cutoff_day or any(
                        e.get('at') and datetime.fromisoformat(e['at'].replace('Z', '+00:00')) > cutoff
                        for e in first):
                    record.update(status='PENDING_FIRST_PUBLICATION', reasons=['EVENT_AFTER_AUDIT_CUTOFF'])
                else:
                    record.update(status='CONFIRMED_NEW_FIRST_PUBLIC', first_public_date=next(iter(days)))
                if record['status']=='CONFIRMED_NEW_FIRST_PUBLIC':
                    day, issue = first_date(record['events'], evidence(decision.get('firstness_evidence')), cutoff)
                    if issue:
                        record.update(status='PENDING_FIRST_PUBLICATION',first_public_date=None,reasons=[issue])
        record['source_records'] = refs
        records.append(record)
    confirmed = [r for r in records if r['status'] == 'CONFIRMED_NEW_FIRST_PUBLIC']
    by_source={(r['paper_id'],r['benchmark_id']):record for record in records for r in record['source_records']}
    date_overlay=[]
    query_records=list(records)
    for row in source_dates:
        record=by_source.get((row['paper_id'],row['benchmark_id']))
        if record is None:
            record={'entity_id':'unresolved-'+digest([row['paper_id'],row['benchmark_id']])[:24],
                'name':row.get('benchmark_name') or '名称待核','kind':'UNKNOWN','scope':'UNVERIFIED',
                'status':'PENDING_ENTITY_AND_FIRST_PUBLICATION','first_public_date':None,
                'events':[],'reasons':['NO_REVIEWED_BENCHMARK_DATE'],'source_records':[row]}
            query_records.append(record)
        date_overlay.append({**row,'entity_id':record['entity_id'],**date_assessment(record)})
    queue = [r for r in records if r['status'].startswith('PENDING')]
    by_day = defaultdict(list)
    for row in confirmed:
        if period_start <= row['first_public_date'] < period_end:
            by_day[row['first_public_date']].append(row['entity_id'])
    # An evaluated-paper snapshot is never an exhaustive new-release census.
    # A blank day therefore cannot be published as a verified zero, even when
    # every record in a small evidence registry has been reviewed.
    days = []
    for offset in range((end-start).days):
        day = (start+timedelta(days=offset)).isoformat()
        ids = sorted(by_day[day])
        days.append({'date': day, 'confirmed_minimum': len(ids), 'daily_total': None,
                     'coverage': 'INCOMPLETE', 'display': f'至少 {len(ids)} 个' if ids else '待核',
                     'entity_ids': ids})
    report = {'policy': POLICY, 'snapshot_id': snapshot_id, 'source_sha256': source_sha256,
              'source_generated_at': source_generated_at, 'as_of': as_of,
              'registry_sha256': digest(registry), 'timezone': 'Asia/Shanghai',
              'period': {'start': period_start, 'end_exclusive': period_end},
              'unit': 'DISTINCT_BENCHMARK_FIRST_PUBLIC_INTRODUCTION',
              'coverage': 'INCOMPLETE', 'daily_total_is_known': False,
              'confirmed_minimum_in_period': sum(d['confirmed_minimum'] for d in days),
              'period_total': None, 'daily_average': None,
              'unallocated_pending_entities': len(queue),
              'pending_scope': 'ENTIRE_SOURCE_SNAPSHOT_UNALLOCATED_NOT_PERIOD_TOTAL',
              'unclassified_evaluation_records': unclassified_evaluations,
              'source_records': len(seen), 'source_date_bases': dict(sorted(date_bases.items())),
              'benchmark_date_coverage': dict(sorted(Counter(r['benchmark_date_status'] for r in date_overlay).items())),
              'dispositions': dict(sorted(Counter(r['status'] for r in records).items())),
              'days': days,
              'notice': '只统计已核实的新benchmark首次公开事件。论文代理日期不计首发；待核不等于零。'
                        '该论文评测快照不代表全网发布量，不能据此计算真实日均。'}
    generation = digest({'report': report, 'entities': records, 'date_overlay': date_overlay})[:24]
    return {'generation': generation, 'daily': report, 'entities': records,
            'review_queue': queue, 'date_overlay':date_overlay, 'query_records':query_records}
