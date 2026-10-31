"""Build one public static generation from the exact remote publication, offline."""
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def build(feed, site, rules_path):
    report = json.loads((feed / 'publication.json').read_text())
    raw = (feed / 'source.json.gz').read_bytes()
    rules_raw = (feed / 'task-measurements.json.gz').read_bytes()
    assert report['publisher'] == 'radar-publication-v1'
    assert len(raw) == report['source_bytes'] and hashlib.sha256(raw).hexdigest() == report['source_sha256']
    assert len(rules_raw) == report['rules_bytes'] and hashlib.sha256(rules_raw).hexdigest() == report['rules_sha256']
    snapshot = json.loads(gzip.decompress(raw))
    rules = json.loads(gzip.decompress(rules_raw))
    sid = snapshot['snapshot_id']
    assert re.fullmatch(r'[a-f0-9]{24}', sid)
    assert sid == report['snapshot_id'] == rules['snapshot_id']
    assert snapshot['index']['method']['version'] in (15,16)
    assert len(snapshot['observations']) == report['observations'] > 0
    root = site / 'snapshot' / sid
    (root / 'details').mkdir(parents=True, exist_ok=True)
    # These archives are retained for audit. Normal browsing uses build-ranking.cjs projections.
    parts = []
    for i, offset in enumerate(range(0, len(raw), 4 * 1024 * 1024)):
        p = root / f'part-{i:03d}.bin'
        value = raw[offset:offset + 4 * 1024 * 1024]
        p.write_bytes(value)
        parts.append({'path': p.relative_to(site).as_posix(), 'bytes': len(value)})
    overview = {k: snapshot[k] for k in ('snapshot_id', 'generated_at', 'window', 'status', 'benchmarks')}
    overview.update(observations=[], index={'models': [], 'groups': []}, score_groups=[], detail_loaded=False,
        capability_annotations={'items': []}, capability_atlas=snapshot.get('capability_atlas'))
    (root / 'overview.json.gz').write_bytes(gzip.compress(encode(overview), mtime=0))
    buckets = {k: defaultdict(list) for k in ('observations', 'metric_groups', 'capability_annotations')}
    for field, rows in [('observations', snapshot['observations']),
                        ('metric_groups', snapshot.get('score_groups', snapshot['index']['groups'])),
                        ('capability_annotations', snapshot.get('capability_annotations', {}).get('items', []))]:
        for row in rows:
            buckets[field][row.get('paper_id'), row.get('benchmark_id')].append(row)
    details = {}
    for b in snapshot['benchmarks']:
        key = b['paper_id'], b['benchmark_id']
        identity = encode(list(key))
        detail = {k: snapshot[k] for k in ('snapshot_id', 'generated_at', 'window')}
        detail.update(benchmark=b, task_matches=[], task_comparisons=[])
        for field in buckets:
            detail[field] = buckets[field][key]
        target = root / 'details' / (hashlib.sha256(identity).hexdigest()[:32] + '.json.gz')
        target.write_bytes(gzip.compress(encode(detail), mtime=0))
        details[identity.decode()] = target.relative_to(site).as_posix()
    manifest = {'format': 'radar-static-snapshot-v1', 'snapshot_id': sid,
        'generated_at': snapshot['generated_at'], 'workspace_sha256': report['source_sha256'], 'parts': parts,
        'overview': (root / 'overview.json.gz').relative_to(site).as_posix(), 'details': details,
        'source_sha256': report['source_sha256'], 'observations': report['observations'], 'method_version': snapshot['index']['method']['version'],
        'score_version': snapshot['index']['method'].get('score_version'), 'model_calls': 0,
        'automatic_publication': True}
    if report.get('task_inputs_sha256'):
        task_raw = (feed / 'task-inputs.json.gz').read_bytes()
        assert len(task_raw) == report['task_inputs_bytes']
        assert hashlib.sha256(task_raw).hexdigest() == report['task_inputs_sha256']
        task = json.loads(gzip.decompress(task_raw))
        assert task['snapshot_id'] == sid and task['format'] == 'radar-task-inputs-v1'
        task_path = root / 'task-inputs.json.gz'
        task_path.write_bytes(task_raw)
        manifest['task_inputs'] = {'path': task_path.relative_to(site).as_posix(), 'bytes': len(task_raw),
                                  'sha256': report['task_inputs_sha256'], 'snapshot_id': sid}
    (site / 'snapshot/manifest.json').write_bytes(encode(manifest))
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_bytes(gzip.decompress(rules_raw))
    print(json.dumps({'snapshot_id': sid, 'observations': len(snapshot['observations']),
        'detail_pages': len(details), 'raw_scores_unchanged': True, 'model_calls': 0}))


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path('site'), Path('validation/task-measurements-v8-real.json'))
