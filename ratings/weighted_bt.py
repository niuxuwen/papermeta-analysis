"""Screenshot specification: batch weighted Bradley--Terry, no hidden penalties."""
import math
from collections import defaultdict
from itertools import combinations
from numerical_solver import fit_graph,sigmoid,objective
from metric_semantics import check_direction
def pair_records(groups, paper_weights=None, benchmark_beta=None, projections=None, *, default_paper_weight=1., default_beta=1., soft=False):
    paper_weights=paper_weights or {};benchmark_beta=benchmark_beta or {};records=[];excluded=defaultdict(int);prepared=[]
    for g in groups:
        if check_direction(g)['status'] in {'CONFLICT','REVIEW_REQUIRED'}:
            excluded['metric_direction_requires_review']+=1;continue
        if not g.get('source_quality',{}).get('eligible',True):
            excluded['source_quality_excluded']+=1;continue
        if g.get('blocked_reasons')or g.get('extraction_in_progress')or g.get('direction')not in {'higher','lower'}:
            excluded['source_not_comparable']+=1;continue
        meta=(projections or {}).get(g['group_id'])
        if meta is not None and not meta.get('capabilities'):
            excluded['not_final_performance']+=1;continue
        allowed=set(meta['models'])if meta is not None else None
        scores=[s for s in g['scores']if (allowed is None or s['model_canonical']in allowed)and math.isfinite(s['value_numeric'])]
        if len({(s['model_canonical'],s.get('dedup_condition',g.get('model_setting','')))for s in scores})!=len(scores):
            excluded['conflicting_model_axis']+=1;continue
        prepared.append((g,scores))
    if soft:
        from soft_outcomes import rms_scales, outcome
        scales=rms_scales(prepared)
    for g,scores in prepared:
        w=float(paper_weights.get(g['paper_id'],default_paper_weight));bid=g.get('benchmark_identity')or g['benchmark_id'];beta=float(benchmark_beta.get(bid,default_beta))
        if not math.isfinite(w)or w<=0 or not math.isfinite(beta)or beta<=0:raise ValueError('Weights and beta must be finite and positive')
        for a,b in combinations(sorted(scores,key=lambda s:s['model_canonical']),2):
            delta=(a['value_numeric']-b['value_numeric'])*(1 if g['direction']=='higher'else -1)
            setting=g.get('model_setting','')or g.get('source_condition_key','')
            an=(a['model_canonical'],a.get('dedup_condition',setting));bn=(b['model_canonical'],b.get('dedup_condition',setting))
            if an==bn:continue
            y,detail=outcome(g,a,b,scales) if soft else (1. if delta>0 else 0. if delta<0 else .5,None)
            record={'a':an,'b':bn,'y':y,'w':w,'beta':beta,'paper_id':g['paper_id'],'benchmark_id':bid,'group_id':g['group_id']}
            if detail is not None:
                detail.update(source_a=an,source_b=bn,source_y=y)
                record['outcome_audit']=detail
            records.append(record)
    return records,dict(excluded)

def components(adjacency):
    seen=set();found=[]
    for start in range(len(adjacency)):
        if start in seen:continue
        pending=[start];seen.add(start);part=[]
        while pending:
            n=pending.pop();part.append(n)
            for other in adjacency[n]:
                if other not in seen:seen.add(other);pending.append(other)
        found.append(part)
    return found

def strongly_connected(adj,rev,ids):
    seen=set();stack=[ids[0]]
    while stack:
        n=stack.pop()
        if n in seen:continue
        seen.add(n);stack.extend(x for x in adj[n]if x not in seen)
    if len(seen)!=len(ids):return False
    seen=set();stack=[ids[0]]
    while stack:
        n=stack.pop()
        if n in seen:continue
        seen.add(n);stack.extend(x for x in rev[n]if x not in seen)
    return len(seen)==len(ids)

def mutual_components(records):
    names=sorted({r[k]for r in records for k in ('a','b')});pos={n:i for i,n in enumerate(names)}
    adj=[set()for _ in names];rev=[set()for _ in names]
    for r in records:
        a,b=pos[r['a']],pos[r['b']]
        if r['y']>0:adj[a].add(b);rev[b].add(a)
        if r['y']<1:adj[b].add(a);rev[a].add(b)
    seen=set();order=[]
    for start in range(len(names)):
        if start in seen:continue
        seen.add(start);stack=[(start,iter(sorted(adj[start])))]
        while stack:
            n,it=stack[-1]
            try:other=next(it)
            except StopIteration:order.append(n);stack.pop();continue
            if other not in seen:seen.add(other);stack.append((other,iter(sorted(adj[other]))))
    seen=set();parts=[]
    for start in reversed(order):
        if start in seen:continue
        stack=[start];part=[];seen.add(start)
        while stack:
            n=stack.pop();part.append(names[n])
            for other in sorted(rev[n]):
                if other not in seen:seen.add(other);stack.append(other)
        parts.append(sorted(part))
    return sorted(parts,key=lambda part:(-len(part),part))

def fit(records,basket=()):
    names=sorted({r[k]for r in records for k in ('a','b')});pos={n:i for i,n in enumerate(names)}
    if not records:return {'status':'NO_COMPARISONS','components':[],'models':[]}
    combined=defaultdict(lambda:[0.,0.]);adj=[set()for _ in names];rev=[set()for _ in names];weak=[set()for _ in names]
    for r in records:
        a,b=pos[r['a']],pos[r['b']];v=combined[a,b,r['beta']];v[0]+=r['w']*r['y'];v[1]+=r['w'];weak[a].add(b);weak[b].add(a)
        if r['y']>0:adj[a].add(b);rev[b].add(a)
        if r['y']<1:adj[b].add(a);rev[a].add(b)
    out=[];models=[]
    for component,ids in enumerate(components(weak)):
        members=[names[i]for i in ids];local={v:i for i,v in enumerate(ids)};audit={'component':component,'models':len(members)}
        if not strongly_connected(adj,rev,ids):
            audit.update(status='NO_FINITE_MLE',reason='Directed positive-win graph is not strongly connected',model_names=[list(n)for n in members]);out.append(audit);continue
        data=[(local[a],local[b],beta,v[0]/v[1],v[1])for(a,b,beta),v in combined.items()if a in local and b in local]
        betas={v[2]for v in data}
        if betas=={1.}:
            edges=[(a,b,y,w)for a,b,_,y,w in data]
            theta,info=fit_graph({'edges':edges,'priors':[0.]*len(ids)},max_iterations=200)
            loss=objective(theta,edges,[0.]*len(ids))
        else:
            theta,info,loss=fit_with_beta(len(ids),data)
        if not info['converged']:raise ArithmeticError('Unpenalized likelihood did not converge')
        center=sum(theta)/len(theta);theta=[t-center for t in theta];anchors=[i for i,nm in enumerate(members)if nm[0]in basket and not nm[1]];ready=len(anchors)==len(basket)and bool(basket)
        for i,name in enumerate(members):
            score=100*sum(sigmoid(theta[i]-theta[j])for j in anchors)/len(anchors)if ready else None
            models.append({'model':name[0],'setting':name[1],'component':component,'elo_scale':1000+400/math.log(10)*theta[i],'theta':theta[i],'basket_score_0_100':score})
        audit.update(status='FINITE_MLE',negative_log_likelihood=loss,optimizer_iterations=info['iterations'],basket_available=ready,basket_found=len(anchors));out.append(audit)
    return {'status':'FINITE_MLE'if all(x['status']=='FINITE_MLE'for x in out)else 'PARTIAL_OR_UNBOUNDED','components':out,'models':sorted(models,key=lambda m:(m['component'],-m['elo_scale'])),'formula':'P=1/(1+10**(beta_b*(R_B-R_A)/400)); maximize sum w_p*(y*log(P)+(1-y)*log(1-P))','regularization':0,'within_paper_normalization':False,'recency_weighting':False,'reference_basket':list(basket),'identifiability':'Within each connected component only; theta mean zero merely chooses its origin.'}

def fit_with_beta(n,data):
    from numerical_solver import _solve,_softplus
    theta=[0.]*n
    def loss(t):return sum(w*(_softplus(beta*(t[a]-t[b]))-y*beta*(t[a]-t[b]))for a,b,beta,y,w in data)
    for iteration in range(1,201):
        grad=[0.]*n;curvature=[]
        for a,b,beta,y,w in data:
            p=sigmoid(beta*(theta[a]-theta[b]));d=w*beta*(p-y);grad[a]+=d;grad[b]-=d;curvature.append((a,b,w*beta*beta*p*(1-p)))
        error=max(map(abs,grad))
        if error<1e-9:return theta,{'converged':True,'iterations':iteration},loss(theta)
        step=_solve([0.]*n,curvature,grad);old=loss(theta);descent=sum(g*s for g,s in zip(grad,step));rate=1.
        while rate>=2**-30:
            updated=[t-rate*s for t,s in zip(theta,step)]
            if loss(updated)<=old-1e-4*rate*descent+1e-12:theta=updated;break
            rate/=2
        else:raise ArithmeticError('Unpenalized beta likelihood line search failed')
    return theta,{'converged':False,'iterations':200},loss(theta)

