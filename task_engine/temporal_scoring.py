from __future__ import annotations

from collections import Counter, defaultdict

from datetime import datetime, timezone

import math

POLICY = 'bounded-benchmark-recency-v1'

HALF_LIFE_DAYS = 90.

FLOOR = .5

def utc_date(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).date() if parsed.tzinfo else parsed.date()
    except ValueError:
        return None

def attach_recency(index, catalog=None, *, as_of=None, half_life_days=HALF_LIFE_DAYS):
    if half_life_days is not None and (not math.isfinite(half_life_days) or half_life_days <= 0):
        raise ValueError('Recency half life must be positive or None (disabled)')
    anchor = utc_date(as_of)
    if as_of is not None and anchor is None:
        raise ValueError('Invalid scoring as-of date')
    enabled = anchor is not None and half_life_days is not None
    by_source = {(b['paper_id'], b['benchmark_id']): b for b in catalog or []}
    candidates = defaultdict(list)
    for g in index['groups']:
        b = by_source.get((g['paper_id'], g['benchmark_id']), {})
        identity = g.get('benchmark_identity', g['benchmark_id'])
        date = utc_date(b.get('release_date'))
        basis = b.get('date_basis')
        if date is not None and basis in ('EXPLICIT_RELEASE', 'PAPER_V1_PROXY'):
            candidates[identity].append((date, basis, g['paper_id'], g['benchmark_id']))
    resolved = {}
    for identity, rows in candidates.items():
        # An earlier proxy is conservative even when a later paper asserts a
        # release. Do not let a later citation or re-release refresh this ID.
        date = min(row[0] for row in rows)
        sources = sorted(set((p, b) for d, _, p, b in rows if d == date))
        basis = 'EXPLICIT_RELEASE' if any(d == date and k == 'EXPLICIT_RELEASE' for d, k, _, _ in rows) else 'PAPER_V1_PROXY'
        resolved[identity] = (date, basis, sources)
    counts = Counter()
    for g in index['groups']:
        identity = g.get('benchmark_identity', g['benchmark_id'])
        date, basis, sources = resolved.get(identity, (None, 'DATE_UNKNOWN', []))
        age = (anchor - date).days if anchor is not None and date is not None else None
        status = basis if age is not None and age >= 0 else 'FUTURE_DATE' if age is not None else 'DATE_UNKNOWN'
        factor = (FLOOR + (1-FLOOR)*2**(-age/half_life_days) if status in ('EXPLICIT_RELEASE', 'PAPER_V1_PROXY') else FLOOR) if enabled else 1.
        g['temporal_weight'] = factor
        g['temporal_provenance'] = dict(policy=POLICY, status=status if enabled else 'DISABLED',
            date_basis=basis, release_date=date.isoformat() if date else None,
            age_days=age, source_keys=[list(s) for s in sources])
        counts[g['temporal_provenance']['status']] += 1
    return dict(policy=POLICY, enabled=enabled, as_of=anchor.isoformat() if anchor else None,
        date_precision='UTC_DAY', half_life_days=half_life_days, floor=FLOOR,
        unknown_or_future_weight=FLOOR, counts=dict(counts),
        formula='0.5 + 0.5 * 2 ** (-age_days / half_life_days)',
        date_policy='Earliest supported release per exact benchmark identity. PAPER_V1_PROXY is explicitly provisional. Unknown/future dates use the floor; no wall-clock fallback.',
        normalization='Recency enters task source mass before macro-task normalization; all final task factors <=1. Neutral and coupling penalties use the same budget scale.')
