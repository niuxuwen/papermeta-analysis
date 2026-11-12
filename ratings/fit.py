from collections import Counter, defaultdict
import math
import re
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

def admissible(records,min_papers,mutual_components):
    """Require actual usable papers after peer/core removal; repeat to a fixed point."""
    current=list(records);rounds=[]
    while current:
        papers=defaultdict(set)
        for r in current:
            papers[r['a']].add(r['paper_id']);papers[r['b']].add(r['paper_id'])
        keep={n for n,p in papers.items()if len(p)>=min_papers}
        subset=[r for r in current if r['a']in keep and r['b']in keep]
        parts=mutual_components(subset)
        core=set(parts[0])if parts else set()
        subset=[r for r in subset if r['a']in core and r['b']in core]
        rounds.append({'nodes':len(core),'comparisons':len(subset),
                       'papers':len({r['paper_id']for r in subset})})
        if len(subset)==len(current):return subset,sorted(core),rounds
        current=subset
    return [],[],rounds

def edge_weights(records,paper_quality,alpha):
    """An alpha of 1 gives each paper a total budget proportional to its q."""
    nodes=defaultdict(set)
    for r in records:nodes[r['group_id']].update([r['a'],r['b']])
    m={gid:len(ns)for gid,ns in nodes.items()}
    exposure=Counter()
    for r in records:exposure[r['paper_id']]+=1/(m[r['group_id']]-1)
    raw=np.array([paper_quality[r['paper_id']]/(m[r['group_id']]-1)
                  /exposure[r['paper_id']]**alpha for r in records])
    # Overall weight scale is fixed, so lambda has a comparable meaning across alpha.
    return raw/raw.sum(),dict(exposure)

class BT:
    def __init__(self,names,records,paper_quality,alpha,shrinkage):
        self.names=names;self.n=len(names);self.shrinkage=shrinkage;self.alpha=alpha
        pos={name:i for i,name in enumerate(names)}
        w,self.exposure=edge_weights(records,paper_quality,alpha)
        joined=defaultdict(lambda:[0.,0.])
        for r,weight in zip(records,w):
            a,b=pos[r['a']],pos[r['b']]
            joined[a,b][0]+=weight*r['y'];joined[a,b][1]+=weight
        self.a=np.array([a for a,b in joined],dtype=int)
        self.b=np.array([b for a,b in joined],dtype=int)
        self.w=np.array([value[1]for value in joined.values()])
        self.y=np.array([value[0]/value[1]for value in joined.values()])

    def objective(self,theta):
        delta=theta[self.a]-theta[self.b]
        data_loss=float(np.sum(self.w*(np.logaddexp(0,delta)-self.y*delta)))
        centered=theta-theta.mean()
        penalty=self.shrinkage*float(centered@centered)/(2*self.n)
        e=self.w*(expit(delta)-self.y)
        grad=(np.bincount(self.a,weights=e,minlength=self.n)
              -np.bincount(self.b,weights=e,minlength=self.n))
        grad+=self.shrinkage/self.n*centered
        return data_loss+penalty,grad

    def fit(self,start=None):
        x0=np.zeros(self.n-1)if start is None else np.asarray(start)[1:]-start[0]
        def loss(x):
            value,grad=self.objective(np.r_[0.,x]);return value,grad[1:]
        result=minimize(loss,x0,jac=True,method='L-BFGS-B',
            options={'maxiter':2500,'maxls':40,'gtol':1e-9,'ftol':1e-13,'maxcor':25})
        theta=np.r_[0.,result.x];theta-=theta.mean()
        _,gradient=self.objective(theta)
        if not result.success and max(abs(gradient))>1e-6:raise ArithmeticError(result.message)
        return {'theta':dict(zip(self.names,theta.tolist())),
            'optimizer':{'success':bool(result.success),'iterations':result.nit,
            'max_gradient':float(max(abs(gradient))),'objective':float(result.fun)},
            'alpha':self.alpha,'shrinkage':self.shrinkage}
def export(fit,records,refs,*,min_papers=1):
    theta=fit['theta'];anchors=[(name,'')for name in refs]
    assert all(name in theta for name in anchors)
    papers=defaultdict(set);benches=defaultdict(set)
    for r in records:
        for k in ['a','b']:papers[r[k]].add(r['paper_id']);benches[r[k]].add(r['benchmark_id'])
    rows=[]
    for (name,setting),strength in sorted(theta.items(),key=lambda x:-x[1]):
        rows.append({'model':name,'setting':setting,'theta':strength,
            'elo_scale':1000+400/math.log(10)*strength,
            'basket_score_0_100':float(100*np.mean([expit(strength-theta[ref])for ref in anchors])),
            'papers':len(papers[name,setting]),'benchmarks':len(benches[name,setting]),'logit_source_papers':0})
    # Paper coverage controls presentation, never the fit or exported evidence.
    assert all(row['papers']>=1 for row in rows)
    return rows

SPECS = {'paper-half': ('paper', .5)}
def vendor(node):
    prefixes={'OpenAI':r'^(gpt|chatgpt|o[134](?:\b|[-.]))','Anthropic':'^claude','Google':'^(gemini|gemma|palm)',
              'Qwen':'^qwen','DeepSeek':'^deepseek','Meta':'^(llama|meta[- /])','Moonshot':'^kimi',
              'xAI':'^grok','MiniMax':'^minimax','Z.ai':r'^(glm|zai|z\.ai)','Microsoft':'^(phi|microsoft)',
              'OpenGVLab':'^internvl','Ai2':'^(olmo|molmo)'}
    return next((v for v,p in prefixes.items() if re.match(p,node[0],re.I)),None)

def fitters(train,nodes,q):
    groups=defaultdict(set);ix={v:k for k,v in enumerate(nodes)}
    for r in train:groups[r['group_id']].update((r['a'],r['b']))
    a=np.array([ix[r['a']] for r in train]); b=np.array([ix[r['b']] for r in train]);size=len(nodes)
    a,b,flip=np.minimum(a,b),np.maximum(a,b),a>b
    y=np.array([r['y'] for r in train]);y=np.where(flip,1-y,y)
    raw=np.array([q[r['paper_id']]/(len(groups[r['group_id']])-1) for r in train])
    uv,pair=np.unique(a*size+b,return_inverse=True)
    factor={}
    for mode in ('benchmark','paper'):
        keys=[(r['paper_id'],r['benchmark_id'] if mode=='benchmark' else None,int(p)) for r,p in zip(train,pair)]
        counts=Counter(keys)
        factor[mode]=np.array([1/counts[k] for k in keys])
    def fit(key, *, shrinkage=0.):
        mode,power=SPECS[key]; w=raw if mode is None else raw*factor[mode]**power
        m=BT.__new__(BT);m.names=nodes;m.n=size;m.shrinkage=shrinkage;m.alpha=0.
        m.a,m.b=uv//size,uv%size;mass=np.bincount(pair,weights=w)
        m.y=np.bincount(pair,weights=w*y)/mass;m.w=mass/mass.sum()
        return m.fit()
    return fit
