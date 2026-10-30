"""Publish verified service results to the owned, replaceable live-data branch.

This exports public data only. It does not run extraction, scoring or model calls.
The main source branch is never written. A lease protects concurrent feed updates.
"""
import argparse
import fcntl
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.request

REPOSITORY = 'ssh://git@ssh.github.com:443/niuxuwen/papermeta-analysis.git'


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def public_source(snapshot):
    keys = ('snapshot_id', 'generated_at', 'window', 'benchmarks', 'observations', 'index',
            'score_groups', 'capability_annotations', 'capability_atlas', 'model_registry')
    result = {k: snapshot[k] for k in keys if k in snapshot}
    if not result.get('observations') or not result.get('index', {}).get('models'):
        raise ValueError('Verified publication is not ready')
    if result['index']['method']['version'] != 15:
        raise ValueError('Unreviewed scoring method; previous website remains published')
    source_status = snapshot.get('status', {})
    result['status'] = {'state': 'PUBLICATION', 'jobs': [], 'stale': False,
        'counts': source_status.get('counts', {}),
        'evidence_generated_at': source_status.get('evidence_generated_at', snapshot['generated_at']),
        'task_evidence_revision': source_status.get('task_evidence_revision')}
    for setting in result['index'].get('relative_reference_audit', {}).get('settings', []):
        setting.pop('latent_fit', None)
    # Published source values, scores and labels remain exact. Runtime state does not.
    for b in result['benchmarks']:
        if isinstance(b.get('progress'), dict):
            b['progress'] = {k: v for k, v in b['progress'].items() if k in {
                'state', 'paper_status', 'status', 'observations', 'models', 'source_tables',
                'tables', 'score_records', 'eligible', 'complete', 'has_scores', 'extraction_in_progress'}}
    return result


def credential_scan(raw):
    for pattern in (rb'sk-(?:or-v1-)?[a-zA-Z0-9_-]{28,}', rb'Bearer\s+[A-Za-z0-9_.-]{28,}',
                    rb'"(?:api_key|password|access_token|secret_key|authorization|environment|headers)"\s*:'):
        if re.search(pattern, raw, re.I):
            raise ValueError('Credential pattern found; publication refused')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    root = args.project.resolve()
    state = root / 'deployment/publication'
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / 'publisher.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        sys.path.insert(0, str(root))
        from recent_benchmarks.snapshot_wire import unpack
        from recent_benchmarks.catalog_task_scoring import prepare_inputs
        from recent_benchmarks.task_measurements import projection
        address = json.loads((root / 'deployment/runtime-address.json').read_text())
        ip = ipaddress.ip_address(address['host'])
        if not (ip.is_private or ip in ipaddress.ip_network('100.64.0.0/10')) or address['port'] != 8765:
            raise ValueError('Unexpected Radar backend')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(f'http://{ip}:8765/api/workspace', headers={'Accept-Encoding': 'gzip'})
        with opener.open(req, timeout=150) as response:
            raw = response.read()
            if response.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
        wire = json.loads(raw)
        if wire.get('wire_format'):
            decoded = unpack(wire['payload'])
            snapshot = {**decoded['snapshot'], **{k: wire[k] for k in ('snapshot_id', 'generated_at', 'window', 'status')}}
        else:
            snapshot = wire
        source = public_source(snapshot)
        # Ignore HTTP read time; only evidence, labels, scores and window dates trigger publication.
        fingerprint = hashlib.sha256(encode({k: source.get(k) for k in
            ('benchmarks', 'observations', 'index', 'score_groups', 'capability_annotations', 'model_registry')})).hexdigest()
        previous_file = state / 'last-published.json'
        previous = json.loads(previous_file.read_text()) if previous_file.exists() else {}
        if previous.get('fingerprint') == fingerprint and previous.get('task_inputs_sha256'):
            print('No new verified evidence; website unchanged', flush=True)
            return
        task_index, catalog = prepare_inputs(source['index'], source['benchmarks'], source['observations'])
        rules = projection(task_index, catalog, source['snapshot_id'])
        # Match the visitor's public catalogue policy before exposing task inputs.
        def public_benchmark(b):
            return ((b.get('name_audit') or {}).get('status') != 'REVIEW_REQUIRED'
                and str(b.get('benchmark_name') or '').strip() not in {'名称待核验','名称待核实','名称待确认'}
                and 'EXCLUDED' not in [b.get('eligibility'),b.get('status'),b.get('history_status'),
                                      (b.get('progress') or {}).get('paper_status')])
        public_index, public_catalog = prepare_inputs(source['index'],
            [b for b in source['benchmarks'] if public_benchmark(b)], source['observations'])
        task_inputs = {k: source[k] for k in ('snapshot_id','generated_at','window')}
        task_inputs.update(format='radar-task-inputs-v1', task_method_version=8,
                           index=public_index, catalog=public_catalog,
                           measurements=projection(public_index, public_catalog, source['snapshot_id']))
        task_bytes = encode(task_inputs)
        credential_scan(task_bytes)
        source_bytes, rule_bytes = encode(source), encode(rules)
        credential_scan(source_bytes)
        credential_scan(rule_bytes)
        packed = gzip.compress(source_bytes, compresslevel=6, mtime=0)
        packed_rules = gzip.compress(rule_bytes, compresslevel=6, mtime=0)
        packed_tasks = gzip.compress(task_bytes, compresslevel=6, mtime=0)
        feed = state / 'feed'
        feed.mkdir(exist_ok=True)
        env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'RADAR_NETWORK_ENV': str(root / 'deployment/network.env')}
        env['GIT_SSH_COMMAND'] = shlex.join(['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(state / 'known_hosts'),
            '-o', 'ProxyCommand=python3 ' + shlex.quote(str(state / 'github_connect.py')) + ' %h %p',
            '-i', str(state / 'github_deploy_ed25519')])
        def git(*argv, check=True, data=None):
            result = subprocess.run(['git', '-C', str(feed), *argv], env=env, input=data,
                capture_output=True, timeout=240)
            if check and result.returncode:
                raise RuntimeError('Publication Git operation failed: ' + argv[0] + ' ' + result.stderr.decode(errors='replace')[-400:])
            return result
        if not (feed / '.git').exists():
            git('init')
            git('remote', 'add', 'origin', REPOSITORY)
            git('config', 'user.name', 'Radar Public Data')
            git('config', 'user.email', 'radar-publication@users.noreply.github.com')
        if git('remote', 'get-url', 'origin').stdout.decode().strip() != REPOSITORY:
            raise ValueError('Unexpected publication repository')
        git('fetch', '--depth=1', 'origin', 'main')
        main_revision = git('rev-parse', 'FETCH_HEAD').stdout.decode().strip()
        workflow = git('show', main_revision + ':.github/workflows/pages.yml').stdout
        if b'live-data' not in workflow:
            raise ValueError('Live publication workflow has not been installed')
        old = git('ls-remote', '--heads', 'origin', 'refs/heads/live-data').stdout.decode().split()
        old_revision = old[0] if old else ''
        if old_revision:
            git('fetch', '--depth=1', 'origin', 'live-data')
            marker = git('show', 'FETCH_HEAD:feed/publication.json', check=False)
            if marker.returncode or json.loads(marker.stdout).get('publisher') != 'radar-publication-v1':
                raise ValueError('Existing branch is not owned by this publisher')
        directory = feed / 'feed'
        directory.mkdir(exist_ok=True)
        (directory / 'source.json.gz').write_bytes(packed)
        (directory / 'task-measurements.json.gz').write_bytes(packed_rules)
        (directory / 'task-inputs.json.gz').write_bytes(packed_tasks)
        report = {'publisher': 'radar-publication-v1', 'snapshot_id': source['snapshot_id'],
            'generated_at': source['generated_at'], 'fingerprint': fingerprint,
            'source_sha256': hashlib.sha256(packed).hexdigest(), 'source_bytes': len(packed),
            'rules_sha256': hashlib.sha256(packed_rules).hexdigest(), 'rules_bytes': len(packed_rules),
            'task_inputs_sha256': hashlib.sha256(packed_tasks).hexdigest(), 'task_inputs_bytes': len(packed_tasks),
            'observations': len(source['observations']), 'method_version': 15, 'model_calls': 0}
        (directory / 'publication.json').write_bytes(encode(report))
        workflow_file = feed / '.github/workflows/pages.yml'
        workflow_file.parent.mkdir(parents=True, exist_ok=True)
        workflow_file.write_bytes(workflow)
        # A separate index and parentless feed commit keep source history and old data out of this branch.
        git('read-tree', '--empty')
        git('add', '--', 'feed', '.github/workflows/pages.yml')
        tree = git('write-tree').stdout.decode().strip()
        revision = git('commit-tree', tree, data=('Verified public data ' + source['generated_at'] + '\n').encode()).stdout.decode().strip()
        git('push', '--force-with-lease=refs/heads/live-data:' + old_revision, 'origin', revision + ':refs/heads/live-data')
        previous_file.write_bytes(encode({**report, 'commit': revision, 'published_at': time.time()}))
        print(encode({**report, 'commit': revision}).decode(), flush=True)


if __name__ == '__main__':
    main()
