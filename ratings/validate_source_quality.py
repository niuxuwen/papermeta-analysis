"""End-to-end real-snapshot replay without writing the published site."""
import argparse,gzip,json,hashlib,sys,math
from pathlib import Path
from unittest.mock import patch
from collections import Counter
import build_elo as main_board
from build_capability_rankings import category_evidence, MIN_CATEGORY_PAPERS, add_category_scores
from source_quality import filter_board_records,registry,norm

def run(output):
    output.mkdir(parents=True,exist_ok=True)
    site=main_board.SITE;manifest=main_board.load(site/'snapshot/current.json')
    source=b''.join((site/p['path']).read_bytes() for p in manifest['parts'])
    assert hashlib.sha256(source).hexdigest()==manifest['source_sha256']
    feed=output/'feed';feed.mkdir(exist_ok=True);(feed/'source.json.gz').write_bytes(source)
    raw=(site/manifest['task_inputs']['path']).read_bytes();original_hash=hashlib.sha256(raw).hexdigest()
    sys.argv=[sys.argv[0],str(feed)]
    with patch.object(main_board,'prepare_data',side_effect=lambda d:(d,{})):
        before=main_board.load_elo_inputs()
    after=main_board.load_elo_inputs()
    parents,ae,_,_=category_evidence(after)
    _,be,_,_=category_evidence(before)
    report={'snapshot_id':manifest['snapshot_id'],'task_inputs_sha256':original_hash,'source_quality_policy':after.data['source_quality_policy'],'formula_unchanged':True,'min_papers':5,'production_changed':False,'source_audit':after.exclusions['source_quality_audit'],'boards':{}}
    assert not any('requires_recheck' in e.get('reason','') for e in report['source_audit']['events'])
    assert len([g for g in after.data['index']['groups'] if g['source_quality'].get('verified_reextraction')])==6
    groups={g['group_id']:g for g in after.data['index']['groups']}
    resources=set(registry()['resource_metrics'])
    for name in ['Main',*parents]:
        br=before.comparisons if name=='Main' else be[name];ar=after.comparisons if name=='Main' else ae[name]
        er,ns,bfit=main_board.fit_main_elo(br,before.paper_weights,min_papers=5,quality_board=name)
        fr,fn,afit=main_board.fit_main_elo(ar,after.paper_weights,min_papers=5,quality_board=name)
        assert all(norm(groups[r['group_id']]['metric']) not in resources for r in fr)
        assert all(r['source_quality'].get('eligible',True) for r in fr)
        again,_=filter_board_records(fr,board=name);assert len(again)==len(fr)
        def summary(rows,fit):
            rank=[]
            if fit and name=='Main':
                rank=main_board.export(fit,rows,after.references)
            elif fit:
                pp={n:set() for n in fit['theta']}
                for edge in rows:
                    for n in (edge['a'],edge['b']):pp[n].add(edge['paper_id'])
                rank=[{'model':n[0],'setting':n[1],'theta':v,'elo':1000+400*v/math.log(10),'papers':len(pp[n])} for n,v in sorted(fit['theta'].items(),key=lambda x:-x[1])]
                add_category_scores(rank)
            assert all(r['papers']>=1 for r in rank)
            return {'papers':len({r['paper_id'] for r in rows}),'comparisons':len(rows),'models':len(rank),'ranking':rank}
        report['boards'][name]={'before':summary(er,bfit),'after':summary(fr,afit),'overlap_removals':dict(Counter(x['reason'] for x in filter_board_records(ar,board=name)[1]))}
        (output/'replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
        print(name,{k:{f:b[f] for f in ['papers','comparisons','models']} for k,b in report['boards'][name].items() if k in ['before','after']},flush=True)
    assert MIN_CATEGORY_PAPERS==5
    assert hashlib.sha256((site/manifest['task_inputs']['path']).read_bytes()).hexdigest()==original_hash
    print('PASS: frozen source unchanged; all five builders apply the shared gate',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();run(args.output)
