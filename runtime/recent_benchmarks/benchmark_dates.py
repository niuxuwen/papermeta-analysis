"""Release-date interpretation; source paper proxies are never promoted."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone


def date_assessment(record):
    first = record.get('first_public_date')
    events = deepcopy(record.get('events', []))
    verified = [e for e in events if e.get('evidence_verified') and not e.get('date_issue') and not e.get('after_audit_cutoff')]
    public = [e for e in verified if e.get('proves_public_existence') is True and e.get('publication_verified') is True
              and e['kind'] in {'FIRST_PUBLIC_INTRODUCTION', 'KNOWN_PUBLIC_EXISTENCE',
                                'PUBLIC_ANNOUNCEMENT', 'CODE_RELEASE', 'DATA_RELEASE'}]
    earliest = min((e['beijing_date'] for e in public), default=None)
    # A dated author launch without a time zone can establish only a
    # conservative upper bound in Beijing, never an exact first-public day.
    author_bounds=[]
    for e in events:
        if (e.get('evidence_verified') and not e.get('after_audit_cutoff') and e.get('publication_verified') is True
                and e.get('proves_public_existence') is True and e.get('author_date_claim')):
            try:author_bounds.append((date.fromisoformat(e['author_date_claim'])+timedelta(days=1)).isoformat())
            except ValueError:pass
    earliest=min([v for v in [earliest,*author_bounds] if v],default=None)
    return {
        'registered_date': deepcopy(record.get('registered_date')),
        'benchmark_first_public_date': first,
        'benchmark_date_status': 'VERIFIED_FIRST_PUBLIC' if first else
            ('NOT_A_BENCHMARK' if record.get('status') == 'NOT_A_BENCHMARK' else
             'PUBLIC_BY_BOUND_ONLY' if earliest else 'PENDING'),
        'benchmark_date_basis': 'REVIEWED_FIRST_PUBLIC_EVENT' if first else None,
        'first_public_on_or_before': earliest,
        'first_public_on_or_before_is_exact_first_date': False,
        'author_date_claims': [e for e in events if e.get('author_date_claim')],
        'bound_rule': 'VERIFIED_PUBLIC_EVENT_OR_AUTHOR_LOCAL_DATE_PLUS_ONE_BEIJING_DAY' if earliest else None,
        'code_release_dates': sorted({e['beijing_date'] for e in verified if e['kind']=='CODE_RELEASE' and e.get('publication_verified') is True}),
        'data_release_dates': sorted({e['beijing_date'] for e in verified if e['kind']=='DATA_RELEASE' and e.get('publication_verified') is True}),
        'date_evidence': events,
        'date_review_notes': record.get('review_notes', ''),
        'date_pending_reasons': [] if first else record.get('reasons') or ['EARLIEST_PUBLIC_INTRODUCTION_UNVERIFIED'],
    }


def first_date(events, firstness_verified, cutoff):
    """Return an independently reviewed date or a concrete blocking reason."""
    first = [e for e in events if e['kind']=='FIRST_PUBLIC_INTRODUCTION']
    if not first or not firstness_verified:
        return None, 'FIRST_PUBLICATION_EVIDENCE_INCOMPLETE'
    if any(not e['evidence_verified'] or e['date_issue'] for e in first):
        return None, 'EVENT_DATE_OR_EVIDENCE_UNVERIFIED'
    days = {e['beijing_date'] for e in first}
    if len(days)!=1:
        return None, 'CONFLICTING_FIRST_PUBLICATION_DATES'
    day=next(iter(days))
    if day>cutoff.astimezone(timezone(timedelta(hours=8))).date().isoformat() or any(
            e.get('at') and datetime.fromisoformat(e['at'].replace('Z','+00:00'))>cutoff for e in first):
        return None, 'EVENT_AFTER_AUDIT_CUTOFF'
    public = [e['beijing_date'] for e in events if e.get('evidence_verified')
              and not e.get('date_issue') and e.get('proves_public_existence') is True]
    if public and min(public)<day:
        return None, 'FIRST_INTRODUCTION_AFTER_KNOWN_PUBLIC_EVIDENCE'
    return day, None
