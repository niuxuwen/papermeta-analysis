"""User-authorized operational dating; independent of score validation.

Enable explicitly with RADAR_ALLOW_PAPER_DATE_FALLBACK=1. A register hit is
reused; a missing date uses the associated paper's first-publication timestamp.
No proxy is labeled as a verified global first-public event.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import unicodedata

POLICY = 'user-date-register-paper-fallback-20261117-v1'
BJ = timezone(timedelta(hours=8))


def normalized(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or '')).strip().casefold())


@lru_cache(maxsize=2)
def _table(path, stamp, size):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('policy') != 'benchmark-date-register-paper-fallback-v1':
        raise ValueError('Unrecognized date register')
    index = {}
    for row in data['entries']:
        names = [row['name'], *(row.get('aliases', []) if row.get('identity_basis') == 'REVIEWED_ENTITY' else [])]
        for name in names:
            index.setdefault(normalized(name), []).append(row)
    return index


def table_index():
    path = Path(os.getenv('RADAR_BENCHMARK_DATE_TABLE',
        'deployment/automatic-dates-20261116/state/benchmark-date-table.json')).resolve()
    try:
        s = path.stat()
        return _table(str(path), s.st_mtime_ns, s.st_size)
    except (OSError, ValueError, KeyError):
        return {}


def stamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError('Timestamp lacks timezone')
        return value
    if not isinstance(value, str):
        raise ValueError('Paper publication date is missing')
    if len(value) == 10:
        return datetime.fromisoformat(value).replace(tzinfo=BJ)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Paper publication timestamp lacks timezone')
    return result


def recover_date(benchmark, paper, start, end, *, text=None, index=None):
    if os.getenv('RADAR_ALLOW_PAPER_DATE_FALLBACK') != '1':
        return None
    if benchmark.get('identity_conflict') or benchmark.get('tests_llms') is not True:
        return None
    if text is not None:
        from .novelty import source_quote
        facts = [benchmark, *benchmark.get('evidence', [])]
        if not any(source_quote(row.get('evidence_quote', ''), text) for row in facts):
            return None
    index = table_index() if index is None else index
    matches = {r['benchmark_key']: r for r in index.get(normalized(benchmark.get('name')), [])}
    if len(matches) > 1:
        return None
    entry = next(iter(matches.values()), None)
    if entry and (entry.get('excluded') or entry.get('identity_basis') == 'AMBIGUOUS_REVIEWED_NAME'):
        return None
    try:
        first = stamp(start); last = stamp(end)
        publication = stamp(paper.get('publication_date') or benchmark.get('paper_first_published'))
        if publication >= last:
            return None
        if entry and entry.get('benchmark_date'):
            release = stamp(entry['benchmark_date'])
            basis = entry['date_basis']; fallback = entry.get('date_is_fallback', False)
            for proof in entry.get('date_evidence', []):
                original = proof.get('original_paper_timestamp')
                if fallback and original and stamp(original).astimezone(BJ).date() == release.date():
                    release = stamp(original); break
        else:
            release = publication; basis = 'PAPER_PUBLICATION_FALLBACK'; fallback = True
        if release >= last:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    result = deepcopy(benchmark)
    result.update(date_basis='DATE_REGISTER', release_date=release.isoformat(),
        paper_first_published=paper.get('publication_date') or benchmark.get('paper_first_published'),
        registered_date_policy=POLICY, registered_date_basis=basis, date_is_fallback=fallback,
        registered_date_key=(entry or {}).get('benchmark_key'),
        date_is_verified_first_public=basis == 'VERIFIED_FIRST_PUBLIC',
        admission_policy=POLICY, admission_basis='USER_REGISTERED_DATE',
        eligibility='ELIGIBLE' if first <= release < last else 'EXCLUDED_DATE',
        reason='按登记日期表计算日期窗口；缺日期按用户授权使用论文首次发布日期，回填不代表独立首发核验')
    return result
