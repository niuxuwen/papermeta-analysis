from __future__ import annotations

from collections import Counter, defaultdict

from itertools import combinations

import math

from statistics import fmean

POLICY = 'source-pair-consensus-v1'

def source_key(g):
    return g['paper_id'], g.get('benchmark_identity', g['benchmark_id'])

class PairWeights(dict):
    def __init__(self, averages, pairs, audit):
        super().__init__(averages)
        self.pairs, self.audit = pairs, audit

    def pair(self, gid, a, b):
        return self.pairs[gid, *sorted((a,b))]

def pair_weight(weights, gid, a, b):
    return weights.pair(gid,a,b) if isinstance(weights,PairWeights) else weights[gid]

def source_pair_weights(groups, original):
    """One budget per pair/source; repeated columns and subsets share it.

    Opponent count in a table does not dilute that table's individual pair.
    Each pair's paper and benchmark budgets are <=1 before the <=1 task and
    information factors. One outcome-independent global scale preserves the
    total old likelihood mass and relative neutral regularization. There is
    no longer a per-model/per-paper budget claim.
    """
    count=Counter();pb=defaultdict(set);bp=defaultdict(set);records=[]
    for g in groups:
        paper,bench=source_key(g)
        for a,b in combinations(sorted(s['model_canonical'] for s in g['scores']),2):
            count[a,b,paper,bench]+=1
            pb[a,b,paper].add(bench);bp[a,b,bench].add(paper)
            records.append((g,a,b,paper,bench))
    raw={};old_total=0.
    for g,a,b,paper,bench in records:
        old_total+=original[g['group_id']]
        raw[g['group_id'],a,b]=g['task_balance_factor']*g['reference_profile'].get('information_weight',1.)/(
            count[a,b,paper,bench]*max(len(pb[a,b,paper]),len(bp[a,b,bench])))
    total=math.fsum(raw.values());scale=old_total/total if total else 1.
    if scale>1+1e-10:raise ArithmeticError('Source pair mass unexpectedly smaller than capped group mass')
    pairs={key:w*scale for key,w in raw.items()}
    by_group=defaultdict(list)
    for (gid,a,b),w in pairs.items():by_group[gid].append(w)
    audit=dict(policy=POLICY,global_mass_scale=scale,old_total_mass=old_total,
               new_total_mass=math.fsum(pairs.values()),pair_records=len(pairs),
               budget_unit='model pair per source paper and benchmark; not individual model per source')
    return PairWeights({gid:fmean(ws) for gid,ws in by_group.items()},pairs,audit)
