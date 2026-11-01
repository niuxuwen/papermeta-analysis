"""Predeclared, validation-only cross-source reference network; never publishes scores.

Fixed prior .3, existing source budgets/contrast/recency, no parameter search.
Benchmark and paper identities are unioned BEFORE allocating four folds.
Only related references with the same capability set, catalogue modality set,
model setting and explicit source-condition key may share a latent strength.
This tests transfer of relative references, NOT real task success.
"""
import gzip,hashlib,json,random,sys,time
from collections import defaultdict
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from statistics import fmean
ROOT=Path(__file__).parent
sys.path.insert(0,'D:/FDU/benchmark-radar')
import recent_benchmarks
recent_benchmarks.__path__.insert(0,str(ROOT.parent/'backend/task_rules'))
from recent_benchmarks.global_scoring import prepare_contests,comparison_target
from recent_benchmarks.balanced_scoring import source_weights
from recent_benchmarks.source_balanced_scoring import incident_source_weights
from recent_benchmarks.source_consensus import pair_weight
from recent_benchmarks.shared_task_scoring import fit_graph
from recent_benchmarks.paired_scoring import components
from recent_benchmarks.temporal_scoring import attach_recency

CAPABILITY_POOLING='--capability-pooling'in sys.argv
GATES={'min_predictable_papers':10,'min_pair_coverage':.5,'min_paper_macro_agreement':.6,
       'agreement_ci_lower_above':.5,'paired_gain_ci_lower_above':0.}
def load(name):return json.loads(gzip.decompress((ROOT/name).read_bytes()))
def source_groups(data,task):
 original={g['group_id']:g for g in data['index']['groups']}
 catalog={(b['paper_id'],b['benchmark_id']):b for b in data['catalog']}
 accepted=defaultdict(set)
 for m in task['models']:
  for c in m['score_components']:accepted[c['group_id']].add(m['model_canonical'])
 panels={p['group_id']:p for p in task['panel']};out=[]
 for gid,p in sorted(panels.items()):
  g=deepcopy(original[gid]);g['scores']=[s for s in g['scores']if s['model_canonical']in accepted[gid]]
  if len(g['scores'])<2:continue
  modality=tuple(sorted(catalog[g['paper_id'],g['benchmark_id']]['catalog_labels']['modalities']))
  facet=p['measurement_facet'];kind=p['evidence_kind']
  semantic=tuple(sorted(p['capability_ids'])) if kind=='RELATED_REFERENCE'and facet.startswith('related_reference:')else facet
  semantics=list(semantic)if CAPABILITY_POOLING and isinstance(semantic,tuple)else [semantic]
  g['experiment_buckets']=[(kind,s,modality,g['model_setting'],g.get('source_condition_key',''))for s in semantics]
  out.append(g)
 return out
def family_folds(groups):
 parent={}
 def find(x):
  parent.setdefault(x,x)
  if parent[x]!=x:parent[x]=find(parent[x])
  return parent[x]
 for g in groups:
  a,b=find('p:'+g['paper_id']),find('b:'+g.get('benchmark_identity',g['benchmark_id']))
  if a!=b:parent[max(a,b)]=min(a,b)
 families=defaultdict(list)
 for x in list(parent):families[find(x)].append(x)
 folds={}
 for members in families.values():
  signature='|'.join(sorted(members));fold=int(hashlib.sha256(signature.encode()).hexdigest(),16)%4
  for x in members:
   if x.startswith('p:'):folds[x[2:]]=fold
 return folds,len(families)
def train(groups,catalog,anchor):
 work={'groups':deepcopy(groups)};attach_recency(work,catalog,as_of=anchor)
 settings,_=prepare_contests(work,scope='task');by_bucket=defaultdict(list)
 for gs in settings.values():
  for g in gs:
   g['task_balance_factor']=g['temporal_weight']
   for bucket in g['experiment_buckets']:by_bucket[bucket].append(g)
 fitted={}
 for bucket,gs in by_bucket.items():
  base=source_weights(gs);weights=incident_source_weights(gs,{g['group_id']:base[g['group_id']]*g['task_balance_factor']*g['reference_profile'].get('information_weight',1.)for g in gs})
  names=sorted({s['model_canonical']for g in gs for s in g['scores']});pos={n:i for i,n in enumerate(names)}
  records=[];mean=defaultdict(lambda:[0.,0.]);papers=defaultdict(set)
  for g in gs:
   for a,b in combinations(sorted(g['scores'],key=lambda s:s['model_canonical']),2):
    an,bn=a['model_canonical'],b['model_canonical'];y=comparison_target(g,a,b);w=pair_weight(weights,g['group_id'],an,bn)
    records.append((an,bn,y,w));mean[an][0]+=w*y;mean[an][1]+=w;mean[bn][0]+=w*(1-y);mean[bn][1]+=w
    papers[an].add(g['paper_id']);papers[bn].add(g['paper_id'])
  factor=sum(base[g['group_id']]*g['temporal_weight']for g in gs)/sum(base.values())
  edges=[(pos[a],pos[b],y,w)for a,b,y,w in records]
  theta,info=fit_graph({'edges':edges,'priors':[.3*factor]*len(names)})
  if not info['converged']:raise ArithmeticError('Training network did not converge')
  component={n:i for i,ns in enumerate(components(names,records))for n in ns}
  fitted[bucket]={n:(theta[pos[n]],mean[n][0]/mean[n][1],component[n],len(papers[n]))for n in names}
 return fitted
def interval(values):
 if not values:return [None,None]
 rng=random.Random(20261101);v=list(values);means=sorted(fmean(rng.choices(v,k=len(v)))for _ in range(1000))
 return [means[24],means[974]]
def audit(name,data):
 task=load('task-v12-result-'+name+'.json.gz')['task_index'];groups=source_groups(data,task);folds,nfamilies=family_folds(groups)
 eligible=covered=0;results=defaultdict(list);byfold=[]
 for fold in range(4):
  training=[g for g in groups if folds[g['paper_id']]!=fold];test=[g for g in groups if folds[g['paper_id']]==fold]
  trained=train(training,[b for b in data['catalog']if folds.get(b['paper_id'])!=fold],data['window']['end'])
  train_papers={g['paper_id']for g in training};train_benches={g.get('benchmark_identity',g['benchmark_id'])for g in training}
  assert not train_papers&{g['paper_id']for g in test}
  assert not train_benches&{g.get('benchmark_identity',g['benchmark_id'])for g in test}
  valid=pred=0
  for g in test:
   for a,b in combinations(sorted(g['scores'],key=lambda s:s['model_canonical']),2):
    delta=(a['value_numeric']-b['value_numeric'])*(1 if g['direction']=='higher'else -1)
    if not delta:continue
    valid+=1;contrasts=[]
    for bucket in g['experiment_buckets']:
     estimates=trained.get(bucket,{});ar,br=estimates.get(a['model_canonical']),estimates.get(b['model_canonical'])
     if ar and br and ar[2]==br[2]and min(ar[3],br[3])>=2:
      weight=next((c['weight']for c in task['profile']['capabilities']if c['id']==bucket[1]),1.)
      contrasts.append((ar[0]-br[0],ar[1]-br[1],weight))
    if not contrasts:continue
    pred+=1
    agreement=lambda d:.5 if abs(d)<1e-10 else float(d*delta>0)
    norm=sum(v[2]for v in contrasts)
    results[g['paper_id'],g.get('benchmark_identity',g['benchmark_id'])].append((agreement(sum(v[0]*v[2]for v in contrasts)/norm),agreement(sum(v[1]*v[2]for v in contrasts)/norm)))
  eligible+=valid;covered+=pred;byfold.append({'fold':fold,'eligible_pairs':valid,'predicted_pairs':pred,'training_papers':len(train_papers),'heldout_papers':len({g['paper_id']for g in test})})
 bypaper=defaultdict(list)
 for(p,b),values in results.items():bypaper[p].append((fmean(v[0]for v in values),fmean(v[1]for v in values)))
 means=[(fmean(v[0]for v in values),fmean(v[1]for v in values))for values in bypaper.values()]
 network=[v[0]for v in means];baseline=[v[1]for v in means];gain=[a-b for a,b in means];ci=interval(network);gci=interval(gain)
 agreement=fmean(network)if network else None;coverage=covered/eligible if eligible else 0
 passed=len(means)>=10 and coverage>=.5 and agreement>=.6 and ci[0]>.5 and gci[0]>0
 return {'matched_papers':len(folds),'heldout_families':nfamilies,'predictable_papers':len(means),'eligible_pairs':eligible,'predicted_pairs':covered,'pair_coverage':coverage,'network_paper_macro_direction_agreement':agreement,'network_paper_bootstrap_95pct':ci,'same_pairs_peer_mean_agreement':fmean(baseline)if baseline else None,'paired_macro_gain':fmean(gain)if gain else None,'paired_gain_bootstrap_95pct':gci,'publication_gate_passed':passed,'folds':byfold}
if __name__=='__main__':
 data=load('task-readiness-followup-inputs.json.gz')
 report={'snapshot_id':data['snapshot_id'],'as_of':data['window']['end'],'experimental_only':True,'production_formula_changed':False,'model_calls':0,'prior':.3,'tuning_performed':False,'predeclared_gates':GATES,'cases':{},'limitations':['Related reference transfer, not independently measured real task success.','Exact paper and benchmark identities define leakage families; independently unrecognized aliases may remain.','Catalogue modality and relevance do not establish identical protocols. Unknown protocols remain reference-only.','Paper bootstrap is an internal uncertainty diagnostic, not external validation.']}
 report['variant']='independent_capability_pooling'if CAPABILITY_POOLING else 'exact_capability_set'
 report['variant_design_note']='Capability pooling is a second structural experiment motivated by outcome-free overlap sparsity; it is not an untouched confirmatory test and cannot justify publication from this snapshot alone.'if CAPABILITY_POOLING else 'Exact capability-set transfer, predeclared before evaluation.'
 target=ROOT/('task-v12-cross-source-capability-experiment.json'if CAPABILITY_POOLING else 'task-v12-cross-source-experiment.json');target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 for name in ('coding','medical','law','math','science','data','meeting_audio','web_factcheck'):
  report['cases'][name]=audit(name,data);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(name,json.dumps({k:v for k,v in report['cases'][name].items()if k!='folds'}),flush=True)
