"""Publish release statistics only beside the exact same score snapshot.

Run after build_live.py. No model requests, queue access or score fitting.
"""
import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import re

from build_release_ledger import atomic_bytes, run


def build(feed, site, registry):
    publication = json.loads((feed/'publication.json').read_text(encoding='utf-8'))
    snapshot = json.loads((site/'snapshot/current.json').read_text(encoding='utf-8'))
    if (snapshot.get('snapshot_id') != publication.get('snapshot_id')
            or snapshot.get('source_sha256') != publication.get('source_sha256')):
        raise ValueError('Release report must match the public score snapshot')
    manifest, daily = run(feed/'source.json.gz', feed/'publication.json', registry, site/'releases')
    generation = manifest['generation']
    if not re.fullmatch('[a-f0-9]{24}', generation):
        raise ValueError('Invalid generation path')
    root = site/'releases'
    for name, entry in manifest['files'].items():
        raw = (root/generation/name).read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Release artifact integrity failure: '+name)
    # Readers use one immutable generation, never a mix of daily/ledger files.
    target = generation+'/index.html'
    atomic_bytes(root/'index.html', ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>新 Benchmark 首发核验</title><meta http-equiv="refresh" content="0;url='
        + escape(target, quote=True)+'"><p><a href="'+escape(target, quote=True)
        +'">打开新 Benchmark 首发核验</a></p></html>').encode())
    api=json.loads((root/generation/'api/v1/manifest.json').read_text(encoding='utf-8'))
    api['api_root']='../../'+generation+'/api/v1/'
    atomic_bytes(root/'api/v1/current.json',json.dumps(api,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    atomic_bytes(root/'api/v1/manifest.json',(root/'api/v1/current.json').read_bytes())
    for path in api['direct_entities'].values():
        atomic_bytes(root/'api/v1'/path,(root/generation/'api/v1'/path).read_bytes())
    for name in ['judge.html','judge-client.mjs','benchmark-date-view.mjs']:
        atomic_bytes(root/'api/v1'/name,(root/generation/'api/v1'/name).read_bytes())
    # This runs after edition generation so both language routes retain a link.
    for page, href in [(site/'index.html','./releases/'), (site/'zh/index.html','../releases/')]:
        if not page.exists():
            continue
        text = page.read_text(encoding='utf-8')
        text = re.sub(r'<p id="benchmark-release-link">.*?</p>', '', text, flags=re.S)
        link = '<p id="benchmark-release-link"><a href="'+href+'">新 Benchmark 首发核验（每日已核实下限，待核不等于零）</a></p>'
        if '</main>' not in text:
            raise ValueError('Public homepage has no main landmark')
        atomic_bytes(page, text.replace('</main>',link+'</main>',1).encode())
    return manifest, daily


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('feed', type=Path)
    p.add_argument('--site', type=Path, default=Path(__file__).resolve().parents[1]/'site')
    p.add_argument('--registry', type=Path, default=Path(__file__).with_name('release-evidence.json'))
    a = p.parse_args()
    manifest, daily = build(a.feed,a.site,a.registry)
    print(json.dumps({'snapshot_id':manifest['snapshot_id'],'generation':manifest['generation'],
        'confirmed_minimum':daily['confirmed_minimum_in_period'],
        'pending':daily['unallocated_pending_entities'],'coverage':'INCOMPLETE'}))


if __name__ == '__main__':
    main()
