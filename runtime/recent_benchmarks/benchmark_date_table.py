"""Reusable benchmark date register: look up, revise, then paper-date fallback.

The register implements the user's operational dating rule. It does not turn
paper proxies or known-public bounds into independently verified first dates.
It never changes source evidence, scores, or paper-window selection.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import unicodedata

from .benchmark_dates import date_assessment

POLICY = 'benchmark-date-register-paper-fallback-v1'
BJ = timezone(timedelta(hours=8))
RANK = {'PAPER_PUBLICATION_FALLBACK': 1, 'PRIMARY_PUBLIC_DATE': 2,
        'VERIFIED_FIRST_PUBLIC': 3}


def name_key(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or '')).strip().casefold())


def calendar_day(value, cutoff):
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            day = date.fromisoformat(value).isoformat()
        else:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                return None
            day = stamp.astimezone(BJ).date().isoformat()
        return day if day <= cutoff else None
    except ValueError:
        return None


def build_table(result, previous=None):
    report = result['daily']; cutoff = calendar_day(report['as_of'], '9999-12-31')
    prior = previous or {'policy': POLICY, 'entries': []}
    if prior.get('policy') != POLICY:
        raise ValueError('Unsupported benchmark date register')
    records = result['query_records']
    # Reviewed aliases can bind spelling variants. Equal unreviewed names are
    # an explicit operational grouping assumption, not verified global identity.
    owners = defaultdict(set)
    for r in records:
        if r.get('identity_evidence'):
            for n in [r['name'], *r.get('aliases', [])]:
                owners[name_key(n)].add(r['entity_id'])
    previous_entries = {e['benchmark_key']: e for e in prior['entries']}
    previous_names = defaultdict(set)
    for e in prior['entries']:
        for n in [e['name'], *e.get('aliases', [])]:
            previous_names[name_key(n)].add(e['benchmark_key'])
    groups = defaultdict(list); assignment = {}
    for r in records:
        n = name_key(r['name']); choices = owners.get(n, set())
        if r.get('identity_evidence'):
            prior_keys = previous_names.get(n, set())
            key = next(iter(prior_keys)) if len(prior_keys) == 1 and len(choices) <= 1 else 'entity:' + r['entity_id']
        elif len(choices) == 1:
            key = 'entity:' + next(iter(choices))
        elif len(choices) > 1:
            key = 'ambiguous:' + r['entity_id']
        elif len(previous_names.get(n, set())) == 1:
            key = next(iter(previous_names[n]))
        else:
            key = 'name:' + sha256(n.encode()).hexdigest()[:24]
        groups[key].append(r); assignment[r['entity_id']] = key
    entries = []; changes = []
    # Retain dated entries outside the current paper window for later lookups.
    for key in sorted(set(groups) | set(previous_entries)):
        current = groups.get(key, []); old = previous_entries.get(key)
        if not current:
            entries.append({**old, 'active': False}); continue
        primary = next((r for r in current if r.get('identity_evidence')), current[0])
        aliases = sorted({r['name'] for r in current} | {a for r in current for a in r.get('aliases', [])})
        existing_reviewed = (old or {}).get('newness_reviewed', False)
        refs = {}; choices = []; excluded = []; new_claim = (old or {}).get('newness') == 'SOURCE_NEW_CLAIM'; existing = (old or {}).get('newness') == 'EXISTING_OR_UPDATE'
        for r in current:
            if r['status'] == 'NOT_A_BENCHMARK':
                excluded.append(r)
            existing |= r['status'] in {'EXISTING_OR_UPDATE', 'SOURCE_REPORTED_EXISTING'}
            existing_reviewed |= r['status'] == 'EXISTING_OR_UPDATE'
            new_claim |= r['status'] == 'CONFIRMED_NEW_FIRST_PUBLIC' or r.get('source_novelty') == 'NEW'
            assessed = date_assessment(r)
            for field, basis in [('benchmark_first_public_date', 'VERIFIED_FIRST_PUBLIC'),
                                 ('first_public_on_or_before', 'PRIMARY_PUBLIC_DATE')]:
                day = calendar_day(assessed.get(field), cutoff)
                if day:
                    choices.append((RANK[basis], day, basis, assessed.get('date_evidence', [])))
            for ref in r.get('source_records', []):
                pair = ref['paper_id'], ref['benchmark_id']
                refs[pair] = {k: ref.get(k) for k in ('paper_id', 'benchmark_id', 'arxiv_id',
                    'source_url', 'paper_first_published', 'date_basis')}
                new_claim |= ref.get('novelty') == 'NEW' or ref.get('date_basis') in {'PAPER_V1_PROXY', 'FIRST_DISCLOSURE'}
                existing |= ref.get('novelty') == 'EXISTING'
                day = calendar_day(ref.get('paper_first_published'), cutoff)
                if day:
                    choices.append((1, day, 'PAPER_PUBLICATION_FALLBACK', [{
                        'kind': 'ASSOCIATED_PAPER_DATE', 'date': day,
                        'paper_id': ref['paper_id'], 'url': ref.get('source_url'),
                        'original_paper_timestamp': ref.get('paper_first_published'),
                        'rule': 'USER_AUTHORIZED_PAPER_FIRST_PUBLICATION_FALLBACK'}]))
        if old and old.get('benchmark_date'):
            day = calendar_day(old['benchmark_date'], cutoff)
            if day:
                choices.append((RANK.get(old['date_basis'], 0), day, old['date_basis'], old.get('date_evidence', [])))
        # Stronger evidence replaces a proxy, even when correcting to a later
        # actual announcement day. Within the same basis the earlier date wins.
        selected = min(choices, key=lambda c: (-c[0], c[1])) if choices else None
        if selected and selected[2] == 'VERIFIED_FIRST_PUBLIC':
            earlier_public = [c for c in choices if c[2] == 'PRIMARY_PUBLIC_DATE' and c[1] < selected[1]]
            if earlier_public:
                selected = min(earlier_public, key=lambda c: c[1])
        explicit_inclusion = any(r['status'] == 'CONFIRMED_NEW_FIRST_PUBLIC' for r in current)
        is_excluded = bool(excluded or (old and old.get('excluded') and not explicit_inclusion))
        reason = ('; '.join(sorted({r.get('kind', 'UNKNOWN') + ': ' + str(r.get('review_notes') or r['status'])
                                   for r in excluded})) or (old or {}).get('exclusion_reason')) if is_excluded else None
        entry = {'benchmark_key': key, 'name': primary['name'], 'aliases': aliases,
            'benchmark_date': None if is_excluded else selected[1] if selected else None,
            'date_basis': 'EXCLUDED' if is_excluded else selected[2] if selected else 'MISSING_PAPER_DATE',
            'date_is_fallback': not is_excluded and bool(selected and selected[2] == 'PAPER_PUBLICATION_FALLBACK'),
            'date_evidence': [] if is_excluded else selected[3] if selected else [],
            'excluded': is_excluded, 'exclusion_reason': reason,
            'newness': 'EXISTING_OR_UPDATE' if existing_reviewed or existing and not new_claim else 'SOURCE_NEW_CLAIM' if new_claim else 'UNCLASSIFIED',
            'newness_reviewed': existing_reviewed,
            'identity_basis': 'REVIEWED_ENTITY' if any(r.get('identity_evidence') for r in current) or key.startswith('entity:') else
                'AMBIGUOUS_REVIEWED_NAME' if key.startswith('ambiguous:') else 'NORMALIZED_NAME_ASSUMPTION',
            'entity_ids': sorted(r['entity_id'] for r in current),
            'source_refs': [refs[p] for p in sorted(refs)], 'active': True,
            'first_recorded_at': (old or {}).get('first_recorded_at', report['source_generated_at']),
            'revision': (old or {}).get('revision', 0), 'changes': list((old or {}).get('changes', []))}
        before = {f: (old or {}).get(f) for f in ('benchmark_date', 'date_basis', 'excluded', 'exclusion_reason')}
        after = {f: entry[f] for f in before}
        if old is None or before != after:
            change = {'at': report['source_generated_at'], 'from': before, 'to': after,
                'reason': 'EXCLUDED_BY_REVIEW' if is_excluded else 'DATE_FOUND_OR_EARLIER_DATE_OR_STRONGER_SOURCE'}
            entry['revision'] += 1; entry['changes'].append(change)
            changes.append({'benchmark_key': key, 'name': entry['name'], **change})
        entries.append(entry)
    by_key = {e['benchmark_key']: e for e in entries}
    for r in records:
        e = by_key[assignment[r['entity_id']]]
        r['registered_date'] = {k: e[k] for k in ('benchmark_key', 'benchmark_date', 'date_basis',
            'date_is_fallback', 'excluded', 'exclusion_reason', 'identity_basis', 'newness')}
    for row in result['date_overlay']:
        key = assignment.get(row['entity_id'])
        if key:
            e = by_key[key]
            row.update(registered_date={k: e[k] for k in ('benchmark_key', 'benchmark_date', 'date_basis',
                'date_is_fallback', 'excluded', 'exclusion_reason', 'identity_basis', 'newness')})
    days = []
    for day in report['days']:
        matching = [e for e in entries if e['active'] and not e['excluded'] and e['benchmark_date'] == day['date']]
        claimed = [e for e in matching if e['newness'] == 'SOURCE_NEW_CLAIM' and e['identity_basis'] != 'AMBIGUOUS_REVIEWED_NAME']
        days.append({'date': day['date'], 'registered_benchmarks': len(matching),
            'new_benchmark_claims': len(claimed), 'paper_date_fallbacks': sum(e['date_is_fallback'] for e in claimed),
            'primary_or_reviewed_dates': sum(not e['date_is_fallback'] for e in claimed)})
    active = [e for e in entries if e['active']]
    summary = {'policy': POLICY, 'unit': 'BENCHMARK_DATE_REGISTER_NORMALIZED_NAMES_AND_REVIEWED_ALIASES',
        'source_snapshot_id': report['snapshot_id'], 'source_generated_at': report['source_generated_at'],
        'period': report['period'], 'active_benchmarks': len(active),
        'dated_benchmarks': sum(bool(e['benchmark_date']) for e in active),
        'paper_date_fallbacks': sum(e['date_is_fallback'] for e in active),
        'excluded_benchmarks': sum(e['excluded'] for e in active),
        'missing_dates': sum(not e['excluded'] and not e['benchmark_date'] for e in active),
        'basis_counts': dict(Counter(e['date_basis'] for e in active)), 'days': days,
        'period_new_benchmark_claims': sum(d['new_benchmark_claims'] for d in days),
        'notice': '按日期表登记：先复用已有日期，缺少可用日期时采用关联论文首次发布日期。'
            '新bench按目录新建声明计数；回填、按名称合并和已核实日期分别标注，不代表全网发布总量。'}
    table = {'policy': POLICY, 'source_snapshot_id': report['snapshot_id'],
        'source_sha256': report['source_sha256'], 'summary': summary, 'entries': entries}
    result['date_table'] = table; result['date_table_changes'] = changes
    report['date_register'] = summary
    return table
