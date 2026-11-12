"""Exercise both production entrypoints against a local isolated output site."""
import argparse,json,shutil,sys,hashlib
from pathlib import Path
from unittest.mock import patch
import build_elo
import build_capability_rankings as capability

def run(output):
    source_site=build_elo.SITE;manifest=build_elo.load(source_site/'snapshot/current.json')
    site=output/'site';site.mkdir(parents=True,exist_ok=True)
    for name in ['snapshot/current.json',manifest['task_inputs']['path'],manifest['ranking']['path'],'radar-viz.js']:
        target=site/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source_site/name,target)
    sys.argv=[sys.argv[0],str(output/'feed')]
    with patch.object(build_elo,'SITE',site),patch.object(capability,'SITE',site):
        build_elo.main();capability.main()
    js=(site/'snapshot-elo-data.js').read_text(encoding='utf8');main=json.loads(js.removeprefix('window.snapshotElo = ').removesuffix(';'))
    cats=json.loads((site/'capability-rankings.json').read_text(encoding='utf8'))
    assert main['source_quality_policy']==cats['source_quality_policy']=='source-quality-v1-20261112'
    assert main['coverage_policy']==cats['coverage_policy']=='coverage-display-only-v1'
    assert main['coverage_audit']['coverage_removed_papers']==0
    assert all(r['papers']>=1 for r in main['models'])
    assert all(r['papers']>=1 and (r['score'] is None or 0<=r['score']<=100) for rows in cats['boards'].values() for r in rows)
    assert all(s['min_papers']==5 for s in cats['status'].values())
    report={'policy':main['source_quality_policy'],'entrypoints':['build_elo.main','build_capability_rankings.main'],'output_only':str(site),'production_changed':False,'min_papers':5,'models':{'Main':len(main['models']),**{c:len(rs) for c,rs in cats['boards'].items()}},'files':{name:hashlib.sha256((site/name).read_bytes()).hexdigest() for name in ['snapshot-elo-data.js','capability-rankings.json']}}
    (output/'builder-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('PASS',json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);run(p.parse_args().output)
