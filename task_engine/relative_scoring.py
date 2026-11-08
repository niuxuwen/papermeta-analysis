from __future__ import annotations

def _benchmark(group):
    return group.get('benchmark_identity', group['benchmark_id'])
