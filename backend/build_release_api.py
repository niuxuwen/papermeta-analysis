"""Hash-sharded public JSON judgment API; no dynamic server is needed to query."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from recent_benchmarks.release_judgment import bucket, judgment, query_index


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def artifacts(result, metadata):
    records=result['query_records'];period=result['daily']['period']
    judged={r['entity_id']:judgment(r,period) for r in records}
    index=query_index(records)
    lookups=defaultdict(dict);values=defaultdict(dict)
    for key,ids in index.items():lookups[bucket(key)][key]=ids
    for key,row in judged.items():values[bucket(key)][key]=row
    files={};manifest={**metadata,'format':'benchmark-release-judgment-api-v1',
        'api_root':'./','normalization':'NFKC, trim, lowercase, collapse whitespace; arxiv URL to versionless ID',
        'lookup':{},'judgments':{},'direct_entities':{},
        'source_records':len(result['date_overlay']),'queryable_identities':len(judged),
        'notice':'查询已有证据；未命中、日期代理或不确定匹配均返回待核，不执行联网调查。'}
    for i in range(256):
        key=f'{i:02x}'
        for category,data in [('lookup',lookups[key]),('judgments',values[key])]:
            if not data:
                manifest[category][key]={'empty':True}
                continue
            path=category+'/'+key+'.json';raw=encode({**metadata,'items':data})
            files['api/v1/'+path]=raw
            manifest[category][key]={'path':path,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    reviewed={r['entity_id'] for r in result['entities'] if r.get('identity_evidence')}
    for eid in sorted(reviewed):
        slug=eid if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}',eid) else hashlib.sha256(eid.encode()).hexdigest()
        path='benchmarks/'+slug+'.json'
        files['api/v1/'+path]=encode({**metadata,**judged[eid]})
        manifest['direct_entities'][eid]=path
    files['api/v1/manifest.json']=encode(manifest)
    for name in ['judge-client.mjs','judge.html','benchmark-date-view.mjs']:
        files['api/v1/'+name]=Path(__file__).with_name(name).read_bytes()
    # This archive is the exact same read-only data used by the POST/CLI adapter.
    import gzip
    files['judgment-data.json.gz']=gzip.compress(encode({'metadata':metadata,'judgments':judged,'index':index}),mtime=0)
    return files
