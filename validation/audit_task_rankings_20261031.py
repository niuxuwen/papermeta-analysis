"""Bounded, real-public-snapshot task-ranking audit; never changes scores."""
import gzip, hashlib, json, math, sys, time, uuid, urllib.request
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from statistics import fmean, median

ROOT=Path(__file__).parent
sys.path.insert(0,'D:/FDU/benchmark-radar')
from recent_benchmarks.catalog_task_scoring import score_task
from recent_benchmarks.public_model_registry import model_vendor

ORIGIN='https://cowhors.com'
CASES={
 'coding':'编写和修复Python代码，通过测试验证功能，并遵循指定输出格式。',
 'medical':'整理医学文献，比较研究方法、主要发现与证据，生成注明来源的综述摘要。',
 'math':'解决代数与几何数学题，给出推导步骤，并检查计算结果。',
 'data':'分析实验数据，选择适当统计方法，解释图表、显著性和结论。',
 'extraction':'从发票和业务文档中提取结构化字段，按JSON格式输出并检查字段完整性。',
 'visual':'阅读图片中的图表和文档页面，回答关于数值、趋势和布局的问题。',
 'law':'审查合同条款，识别风险与前后矛盾，引用原文说明修改建议。',
 'science':'回答物理、化学和生物科学问题，推导结论并检查事实准确性。',
}
def read(url,body=None,timeout=90):
    req=urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode()if body is not None else None,
        headers={'Origin':ORIGIN,'Content-Type':'application/json','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=timeout)as r:return json.load(r)
def save(name,value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def vendor(name):return model_vendor(name)['vendor']
def aggregate(result):
    task=result['task_index'];panels=defaultdict(list)
    for m in task['models']:
        if m.get('publication_eligible'):panels[m['panel_id']].append(m)
    matches={(b['paper_id'],b['benchmark_id']):b for b in task['benchmark_matches']}
    pairs=[];cohorts=[]
    for pid,rows in panels.items():
        rows.sort(key=lambda m:-m['publication_score'])
        paper_ids={c['paper_id']for m in rows for c in m['score_components']}
        bm={c['benchmark_identity']for m in rows for c in m['score_components']}
        facets=sorted({f for m in rows for f in m['measurement_facets']})
        cohorts.append({'panel_id':pid,'facets':facets,'models':len(rows),'papers':len(paper_ids),'benchmarks':len(bm),
            'top10':[{'name':m['model_canonical'],'score':m['publication_score'],'benchmarks':m['scored_benchmarks'],
                'measured_weight':m['capability_weight_coverage'],'vendor':vendor(m['model_canonical'])}for m in rows[:10]]})
        for a,b in combinations(rows,2):
            if a['model_canonical']==b['model_canonical']:continue
            ac={c['group_id']:c for c in a['score_components']};bc={c['group_id']:c for c in b['score_components']}
            shared=ac.keys()&bc.keys()
            if not shared:continue
            by_bench=defaultdict(list);common_deltas=[]
            for gid in shared:
                c,d=ac[gid],bc[gid];delta=(c['raw_value']-d['raw_value'])*(1 if c['direction']=='higher'else -1)
                by_bench[c['paper_id'],c['benchmark_identity']].append(.5 if delta==0 else float(delta>0));common_deltas.append(delta)
            votes={str(k):fmean(v)for k,v in by_bench.items()};means=list(votes.values())
            pair={'a':a['model_canonical'],'b':b['model_canonical'],'a_score':a['publication_score'],'b_score':b['publication_score'],
                'same_vendor':vendor(a['model_canonical'])==vendor(b['model_canonical']) and vendor(a['model_canonical'])!='其他 / 厂商待确认',
                'vendor':vendor(a['model_canonical']),'panel_id':pid,'facets':facets,'groups':len(shared),'shared_benchmarks':len(votes),
                'shared_papers':len({k[0]for k in by_bench}), 'a_win_benchmarks':sum(v>.5 for v in means),
                'ties':sum(v==.5 for v in means),'a_loss_benchmarks':sum(v<.5 for v in means),
                'source_agreement':fmean(means),'sources':votes,
                'strict_common_group_dominance_conflict':a['publication_score']>b['publication_score']+1e-8 and all(v<=0 for v in common_deltas)and any(v<0 for v in common_deltas),
                'rank_conflicts_with_all_common_benchmarks':a['publication_score']>b['publication_score']+1e-8 and all(v<=.5 for v in means)and any(v<.5 for v in means)}
            pairs.append(pair)
    pairs.sort(key=lambda p:(not p['rank_conflicts_with_all_common_benchmarks'],-p['shared_papers'],-p['shared_benchmarks'],-(p['a_score']-p['b_score'])))
    suspicious=[]
    for b in task['benchmark_matches']:
        for metric in b['metrics']:
            if __import__('re').search(r'(?i)\b(?:ece|brier|delta|gain|latency|tpr|tnr|fpr|asr|kbs|gcs)\b|[Δδ]',metric):
                suspicious.append({'benchmark':b['benchmark_name'],'metric':metric,'paper_id':b['paper_id'],
                    'benchmark_id':b['benchmark_id'],'group_ids':b['group_ids']})
    vendor_pairs=[p for p in pairs if p['same_vendor']]
    bad=[p for p in vendor_pairs if p['rank_conflicts_with_all_common_benchmarks']]
    repeated=[p for p in bad if p['shared_papers']>=2]
    return {'benchmarks':task['matched_benchmarks'],'models':len({m['model_canonical']for m in task['models']}),
        'panels':len(panels),'papers':len({b['paper_id']for b in task['benchmark_matches']}),
        'match_scope':task['match_scope'],'capability_coverage':task['capability_coverage'],
        'multi_benchmark_panels':sum(c['benchmarks']>1 for c in cohorts),
        'single_benchmark_panels':sum(c['benchmarks']==1 for c in cohorts),'cohorts':cohorts,
        'same_vendor_pairs_with_shared_sources':len(vendor_pairs),'same_vendor_common_source_conflicts':len(bad),
        'same_vendor_repeated_paper_conflicts':len(repeated),
        'strict_same_vendor_dominance_conflicts':[p for p in vendor_pairs if p['strict_common_group_dominance_conflict']],
        'conflict_examples':bad[:20],
        'selected_vendor_comparisons':[p for p in vendor_pairs if p['a'].startswith(('GPT-6','GPT-5.6','Claude 5','Gemini 3','DeepSeek-V4'))and p['b'].startswith(('GPT-6','GPT-5.6','Claude 5','Gemini 3','DeepSeek-V4'))][:120],
        'suspicious_metrics_for_source_review':suspicious,'all_pairs':pairs}

def online():
    manifest=read(ORIGIN+'/snapshot/current.json?task-audit='+uuid.uuid4().hex)
    config=read(ORIGIN+'/task-backend.json');sid=manifest['snapshot_id'];base=config['base_url'].rstrip('/')
    def route(path):return base+'/api/'+path+'?snapshot_id='+sid
    health=read(route('task-service'));assert health['snapshot_id']==sid
    item=manifest['task_inputs']
    with urllib.request.urlopen(ORIGIN+'/'+item['path'],timeout=90)as r:raw=r.read()
    assert len(raw)==item['bytes']and hashlib.sha256(raw).hexdigest()==item['sha256']
    (ROOT/'task-audit-inputs-20261031.json.gz').write_bytes(raw)
    save('task-audit-manifest-20261031.json',manifest)
    report={'snapshot_id':sid,'generated_at':manifest['generated_at'],'method':8,'cases':{},'errors':{}}
    def job(kind,payload):
        j=read(route('interactive-jobs'),{'kind':kind,'payload':payload,'request_id':uuid.uuid4().hex})
        end=time.monotonic()+150
        while time.monotonic()<end:
            value=read(route('interactive-jobs/'+j['id']))
            if value['state']=='COMPLETE':return value['result']
            if value['state']in ('FAILED','CANCELLED'):raise RuntimeError(str(value.get('error',value['state'])))
            time.sleep(1)
        raise TimeoutError('task audit bounded wait exceeded')
    for name,description in CASES.items():
        try:
            start=time.monotonic();profile=job('profile',{'description':description})['profile']
            result=job('score',{'profile':profile,'reference_models':[]})
            assert result['snapshot_id']==sid
            (ROOT/f'task-audit-{name}-20261031.json.gz').write_bytes(gzip.compress(json.dumps(result,ensure_ascii=False).encode()))
            summary=aggregate(result);summary['profile']=profile;summary['seconds']=round(time.monotonic()-start,2)
            report['cases'][name]=summary
            print(name,json.dumps({k:summary[k]for k in ('seconds','benchmarks','models','panels','match_scope','same_vendor_common_source_conflicts','same_vendor_repeated_paper_conflicts')},ensure_ascii=False),flush=True)
        except Exception as exc:
            report['errors'][name]=str(exc);print(name,'FAILED',str(exc),flush=True)
        save('task-ranking-audit-20261031.json',report)
    return report

if __name__=='__main__':online()
