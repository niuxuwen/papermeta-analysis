"""Build an atomic, replayable first-publication ledger from one exact feed.

Read-only input; never opens a queue database or modifies scoring evidence.
Requires ijson for bounded-memory input. The immutable output generation is
written completely before its current.json pointer is replaced.
"""
import argparse
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
from html import escape
import json
import os
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'runtime'))
from recent_benchmarks.release_ledger import BEIJING, build_ledger, digest
from build_release_api import artifacts as api_artifacts


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def atomic_bytes(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def html_report(result):
    d = result['daily']
    rows = ''.join('<tr><td>' + escape(r['date']) + '</td><td>' + escape(r['display'])
                   + '</td><td>未核完</td></tr>' for r in d['days'])
    verified = ''.join('<li>' + escape(r['name']) + ' · ' + escape(r['first_public_date'])
        + ' · <a href="' + escape(next(e['evidence']['url'] for e in r['events']
            if e['kind'] == 'FIRST_PUBLIC_INTRODUCTION'), quote=True) + '">首发证据</a></li>'
        for r in result['entities'] if r['status'] == 'CONFIRMED_NEW_FIRST_PUBLIC'
        and d['period']['start'] <= r['first_public_date'] < d['period']['end_exclusive'])
    return ('''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>新 Benchmark 首发核验</title><style>
body{font:16px/1.7 system-ui,sans-serif;max-width:860px;margin:40px auto;padding:0 20px;color:#173047}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:12px;border-bottom:1px solid #dce5ed}
aside{padding:18px;background:#f1f6fb;border-radius:12px}a{color:#176dc0}</style>
<h1>新 Benchmark 首发核验</h1><aside>''' + escape(d['notice']) + '</aside><p>'
            + escape(d['period']['start']) + ' 至 ' + escape(d['days'][-1]['date'])
            + ' · 北京时间</p><p>整个来源快照中尚有 ' + str(d['unallocated_pending_entities'])
            + ' 个候选身份未完成核验（含尚未跨论文去重的记录）。这是全来源待核池，不是本期新增量，不能按论文日期分配到首发日。</p>'
            + '<table><thead><tr><th>日期</th><th>已核实首发下限</th><th>每日总量</th></tr></thead><tbody>'
            + rows + '</tbody></table><p>已核实条目（不代表全量）：</p><ul>' + verified + '</ul><p>数据快照：'
            + escape(d['snapshot_id']) + ' · ' + escape(d['source_generated_at'])
            + '</p><p><a href="api/v1/judge.html">查询某个 Benchmark 的首发判断与日期</a></p><p><a href="../../">返回总榜</a></p><p><a href="daily.json">下载统计与口径</a> · '
            + '<a href="benchmark-dates.json.gz">下载完整日期补全台账</a> · '
            + '<a href="entities.json.gz">下载实体与发布证据</a> · '
            + '<a href="review-queue.json.gz">下载待核队列</a></p></html>').encode()


def run(source, publication, registry_path, output, *, start=None, end=None, as_of=None):
    try:
        import ijson
    except ImportError as e:
        raise RuntimeError('ijson is required; input is not loaded with an unbounded JSON fallback') from e
    pub = json.loads(publication.read_text(encoding='utf-8'))
    source_hash = file_hash(source)
    if source_hash != pub.get('source_sha256'):
        raise ValueError('Publication/source hash mismatch')
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    # Replaying the same source/registry must not create a new public release
    # generation every five minutes merely because the wall clock advanced.
    as_of = as_of or pub['generated_at']
    clock = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
    if clock.tzinfo is None:
        raise ValueError('as_of must include a time zone')
    end = end or clock.astimezone(BEIJING).date().isoformat()
    start = start or (datetime.fromisoformat(end).date()-timedelta(days=14)).isoformat()
    # The source ID is independently checked, not inferred from the manifest.
    with gzip.open(source, 'rb') as f:
        snapshot_id = next(ijson.items(f, 'snapshot_id'), None)
    if snapshot_id != pub.get('snapshot_id'):
        raise ValueError('Publication/source snapshot mismatch')
    with gzip.open(source, 'rb') as f:
        result = build_ledger(ijson.items(f, 'benchmarks.item', use_float=True), registry,
            snapshot_id=snapshot_id, source_sha256=source_hash,
            source_generated_at=pub['generated_at'], period_start=start,
            period_end=end, as_of=as_of)
    # Renderer/producer changes also create a new immutable generation.
    producer_files=[Path(__file__), Path(sys.modules[build_ledger.__module__].__file__),
        PROJECT/'runtime/recent_benchmarks/benchmark_dates.py',
        PROJECT/'runtime/recent_benchmarks/release_judgment.py',
        Path(__file__).with_name('build_release_api.py'),Path(__file__).with_name('judge-client.mjs'),
        Path(__file__).with_name('judge.html'),Path(__file__).with_name('benchmark-date-view.mjs')]
    producer_hash = hashlib.sha256(b''.join(p.read_bytes() for p in producer_files)).hexdigest()
    result['generation'] = digest({'evidence_generation':result['generation'],
                                   'producer_sha256':producer_hash})[:24]
    dest = output / result['generation']
    dest.mkdir(parents=True, exist_ok=True)
    files = {'daily.json': json_bytes(result['daily']),
             'entities.json.gz': gzip.compress(json_bytes(result['entities']), mtime=0),
             'review-queue.json.gz': gzip.compress(json_bytes(result['review_queue']), mtime=0),
             'benchmark-dates.json.gz': gzip.compress(json_bytes(result['date_overlay']),mtime=0),
             'index.html': html_report(result)}
    metadata={'snapshot_id':snapshot_id,'source_sha256':source_hash,
              'source_generated_at':pub['generated_at'],'report_period':result['daily']['period'],
              'registry_sha256':digest(registry),'generation':result['generation']}
    files.update(api_artifacts(result,metadata))
    manifest = {'format': 'benchmark-first-publication-ledger-v1',
                'generation': result['generation'], 'snapshot_id': snapshot_id,
                'source_sha256': source_hash, 'as_of': as_of,
                'producer_sha256': producer_hash,
                'registry_sha256': digest(registry), 'coverage': 'INCOMPLETE', 'files': {}}
    for name, raw in files.items():
        atomic_bytes(dest/name, raw)
        manifest['files'][name] = {'path': result['generation']+'/'+name,
                                  'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    atomic_bytes(dest/'manifest.json', json_bytes(manifest))
    atomic_bytes(output/'current.json', json_bytes(manifest))
    return manifest, result['daily']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('source', 'publication', 'registry', 'output'):
        p.add_argument('--'+flag, type=Path, required=True)
    p.add_argument('--start', help='Inclusive Beijing calendar date')
    p.add_argument('--end', help='Exclusive Beijing calendar date')
    p.add_argument('--as-of', help='Timezone-aware audit timestamp')
    a = p.parse_args()
    manifest, daily = run(a.source, a.publication, a.registry, a.output,
                          start=a.start, end=a.end, as_of=a.as_of)
    print(json.dumps({'generation': manifest['generation'], 'snapshot_id': manifest['snapshot_id'],
                      'confirmed_minimum': daily['confirmed_minimum_in_period'],
                      'pending': daily['unallocated_pending_entities'],
                      'daily_total': None, 'coverage': 'INCOMPLETE'}, ensure_ascii=True))


if __name__ == '__main__':
    main()
