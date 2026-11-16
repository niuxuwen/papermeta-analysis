"""Query the public benchmark judgment API or an immutable offline ledger."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from recent_benchmarks.release_judgment import answer, bucket, normalize_query


def fetch_bytes(url):
    if urlsplit(url).scheme not in {'https','http'}:
        raise ValueError('API URL must be HTTP or HTTPS')
    with urlopen(url,timeout=30) as response:
        raw=response.read(16*1024*1024+1)
    if len(raw)>16*1024*1024:raise ValueError('API shard exceeds size limit')
    return raw


def query_api(query,manifest_url,*,fetch=fetch_bytes,paper_id=None):
    key=normalize_query(query)
    manifest=json.loads(fetch(manifest_url))
    if manifest.get('format')!='benchmark-release-judgment-api-v1':raise ValueError('Unsupported judgment API')
    root=urljoin(manifest_url,manifest['api_root'])
    if (urlsplit(root).scheme,urlsplit(root).netloc)!=(urlsplit(manifest_url).scheme,urlsplit(manifest_url).netloc):raise ValueError('API origin mismatch')
    def shard(meta):
        if meta.get('empty') is True:return {}
        if not re.fullmatch(r'(lookup|judgments)/[a-f0-9]{2}\.json',meta.get('path','')):
            raise ValueError('Invalid API shard path')
        raw=fetch(urljoin(root,meta['path']))
        if len(raw)!=meta['bytes'] or hashlib.sha256(raw).hexdigest()!=meta['sha256']:
            raise ValueError('Judgment shard integrity failure')
        data=json.loads(raw)
        if any(data.get(k)!=manifest.get(k) for k in ['snapshot_id','source_sha256','registry_sha256','generation']):
            raise ValueError('Judgment API snapshot mismatch')
        return data['items']
    index=shard(manifest['lookup'][bucket(key)])
    judged={}
    for prefix in {bucket(i) for i in index.get(key,[])}:
        judged.update(shard(manifest['judgments'][prefix]))
    metadata={k:manifest[k] for k in ['snapshot_id','source_sha256','source_generated_at','registry_sha256','generation','report_period']}
    return answer(query,judged,index,metadata=metadata,paper_id=paper_id)


def query_offline(query,manifest_path,*,paper_id=None):
    m=json.loads(manifest_path.read_text(encoding='utf-8'))
    entry=m['files']['judgment-data.json.gz']
    path=(manifest_path.parent/entry['path']).resolve()
    if not path.is_relative_to(manifest_path.parent.resolve()):raise ValueError('Archive escapes ledger root')
    raw=path.read_bytes()
    if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
        raise ValueError('Offline judgment archive integrity failure')
    data=json.loads(gzip.decompress(raw))
    if any(data['metadata'].get(k)!=m.get(k) for k in ['snapshot_id','source_sha256','registry_sha256','generation']):
        raise ValueError('Offline judgment snapshot mismatch')
    return answer(query,data['judgments'],data['index'],metadata=data['metadata'],paper_id=paper_id)


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--api',default=None);g.add_argument('--ledger',type=Path)
    p.add_argument('--query',required=True);p.add_argument('--paper-id')
    a=p.parse_args()
    try:
        result=query_offline(a.query,a.ledger,paper_id=a.paper_id) if a.ledger else query_api(
            a.query,a.api or 'https://cowhors.com/releases/api/v1/current.json',paper_id=a.paper_id)
    except Exception as e:
        print(json.dumps({'error':type(e).__name__,'message':str(e),'judgment':'PENDING',
                          'is_new_in_report_period':None},ensure_ascii=False));return 1
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
