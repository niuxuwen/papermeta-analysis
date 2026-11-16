"""Refresh the durable register before optional network date research."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from recent_benchmarks.release_ledger import build_ledger, source_projection, digest, BEIJING
from recent_benchmarks.automatic_date_merge import merge_registries
from recent_benchmarks.benchmark_date_table import build_table


def refresh(reviewer):
    from automatic_date_review import atomic
    envelope = json.loads((reviewer.state/'registry.json').read_text())
    pub = json.loads(reviewer.db.execute('SELECT value FROM meta WHERE key=?', ('publication',)).fetchone()[0])
    rows = [json.loads(t[0]) for t in reviewer.db.execute('SELECT row_json FROM tasks WHERE active=1')]
    signatures = {(r['paper_id'], r['benchmark_id']): digest(source_projection(r)) for r in rows}
    registry, _ = merge_registries(reviewer.manual, envelope, signatures)
    end = datetime.fromisoformat(pub['generated_at'].replace('Z', '+00:00')).astimezone(BEIJING).date()
    result = build_ledger(rows, registry, snapshot_id=pub['snapshot_id'], source_sha256=pub['source_sha256'],
        source_generated_at=pub['generated_at'], period_start=(end-timedelta(days=14)).isoformat(),
        period_end=end.isoformat(), as_of=pub['generated_at'])
    target = reviewer.state/'benchmark-date-table.json'
    previous = json.loads(target.read_text()) if target.exists() else None
    table = build_table(result, previous)
    atomic(target, table)
    atomic(reviewer.state/'benchmark-date-table-summary.json', table['summary'])
    return table['summary']
