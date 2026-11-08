from __future__ import annotations

from collections import defaultdict

import math

from statistics import fmean

from .source_consensus import PairWeights, source_pair_weights

POLICY='incident-capped-source-pairs-v1'

def incident_source_weights(groups,original,*,repeat_strength=0.):
    """Cap each model's paper and benchmark incidence before common scaling.

    Degrees use source incidence only. Task, recency and information factors
    enter after the cap, so a large opponent roster cannot manufacture source
    mass or cancel a benchmark's date weight. A single common multiplier keeps
    the total loss mass comparable with the existing prior and task coupling.
    """
    paired=source_pair_weights(groups,original)
    by_id={g['group_id']:g for g in groups}
    paper,bench=defaultdict(float),defaultdict(float);base={}
    for (gid,a,b),weight in paired.pairs.items():
        g=by_id[gid];factor=g['task_balance_factor']*g['reference_profile'].get('information_weight',1.)
        value=weight/(paired.audit['global_mass_scale']*factor)
        base[gid,a,b]=value
        for name in (a,b):
            paper[name,g['paper_id']]+=value
            bench[name,g.get('benchmark_identity',g['benchmark_id'])]+=value
    sources=defaultdict(set)
    for(gid,a,b)in base:sources[a,b].add(by_id[gid]['paper_id'])
    raw={};pcheck,bcheck=defaultdict(float),defaultdict(float)
    for (gid,a,b),value in base.items():
        g=by_id[gid];pid=g['paper_id'];bid=g.get('benchmark_identity',g['benchmark_id'])
        cap=max(1.,paper[a,pid],paper[b,pid],bench[a,bid],bench[b,bid])
        repeat=len(sources[a,b])/(len(sources[a,b])+repeat_strength)
        value=value/cap*g['task_balance_factor']*g['reference_profile'].get('information_weight',1.)*repeat
        raw[gid,a,b]=value
        for name in(a,b):pcheck[name,pid]+=value;bcheck[name,bid]+=value
    total=math.fsum(raw.values());scale=paired.audit['old_total_mass']/total if total else 1.
    pairs={key:value*scale for key,value in raw.items()};averages=defaultdict(list)
    for(gid,a,b),value in pairs.items():averages[gid].append(value)
    audit=dict(policy=POLICY,repeat_strength=repeat_strength,global_mass_scale=scale,old_total_mass=paired.audit['old_total_mass'],new_total_mass=math.fsum(pairs.values()),
        max_model_paper_budget=max(pcheck.values(),default=0),max_model_benchmark_budget=max(bcheck.values(),default=0),
        budget_unit='model/source incidence capped at 1 before common mass scaling; no outcome or identity prior')
    return PairWeights({gid:fmean(values)for gid,values in averages.items()},pairs,audit)
