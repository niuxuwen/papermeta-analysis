"""Pool explicit effort settings into base model ratings with configuration budgets."""
from collections import defaultdict, Counter
import math,re
from model_dedup import identify

LEVEL=r'none|minimal|low|medium|high|xhigh|max|thinking|non-thinking|nothink|think|adaptive/max'

def base_node(node):
    name,setting=node
    name=re.sub(r'(?i)[ -]+(?:no|non)[ -]*\(thinking\)$','',name).strip()
    name=re.sub(r'(?i)[ -]+extended\s+\(thinking\)$','',name).strip()
    # Parenthesized levels and explicit effort fields are configuration, not names.
    name=re.sub(r'(?i)\s*\((?:reasoning(?: effort)?\s*[:=]?\s*)?(?:'+LEVEL+r')\)', '',name).strip()
    name=re.sub(r'(?i)\s+adaptive/max$', '',name).strip()
    name=re.sub(r'(?i)\s+(?:reasoning|thinking)\s+effort\s*[:=]?\s*(?:'+LEVEL+r')\b','',name).strip()
    # Never strip product designators such as Qwen Max or Mistral Medium.
    name=re.sub(r'(?i)\s+(?:low|high|xhigh|minimal)\s*$', '',name).strip()
    name=re.sub(r'(?i)\s+(?:xhigh|low|high)(?=\s+\d+(?:\.\d+)?[BT]\b)', '',name).strip()
    if re.match(r'(?i)^(?:gpt|claude|gemini|grok|kimi|hy\d|hunyuan|muse spark)',name):
        name=re.sub(r'(?i)\s+(?:medium|max)\s*$', '',name).strip()
    name=re.sub(r'(?i)\s+minimal reasoning$', '',name).strip()
    bits=[]
    for bit in re.split(r'[|;]',setting):
        bit=bit.strip()
        if not bit:continue
        if re.fullmatch(r'(?i)(?:reasoning(?: effort)?\s*[:=]?\s*)?(?:'+LEVEL+r')',bit):continue
        bits.append(bit)
    return name,' | '.join(bits)

def pool_efforts(edges,weights,references=(),measurement_factors=None,measurement_exponent=1.):
    old_nodes=sorted({e[k] for e in edges for k in ('a','b')})
    parsed={n:identify(*base_node(n)) for n in old_nodes}
    buckets=defaultdict(list)
    for n,p in parsed.items():buckets[p['key']].append(n)
    mapping={};registry=[]
    for members in buckets.values():
        preferred=min(members,key=lambda n:(parsed[n]['name'] not in references,
            bool(re.search(r'(?i)^(gpt|claude|gemini|qwen|glm|grok)\d',parsed[n]['name'])),
            parsed[n]['name'].count(' ') if parsed[n]['name'].startswith('GPT-') else 0,
            len(parsed[n]['name']),parsed[n]['name']))
        target=(parsed[preferred]['name'],parsed[preferred]['setting'])
        for n in members:mapping[n]=target
        if len(members)>1 or target!=members[0]:registry.append(dict(model=target,source_configurations=members))
    projected=[];self_edges=[];rosters=defaultdict(set)
    for e in edges:
        a,b=mapping[e['a']],mapping[e['b']]
        if a==b:
            self_edges.append(dict(paper_id=e['paper_id'],group_id=e['group_id'],source_nodes=[e['a'],e['b']]))
            continue
        y=e['y'];variant=(e['a'],e['b'])
        if a>b:a,b,y,variant=b,a,1-y,(e['b'],e['a'])
        row={**e,'a':a,'b':b,'y':y,'effort_variant':variant}
        projected.append(row);rosters[e['paper_id'],e['group_id']].update((a,b))
    # Within each paper/base-model pair, variants share one evidence budget.
    # Each variant retains paper-half weighting over its source measurements;
    # average their total masses instead of adding a new budget per effort.
    by_pair=defaultdict(lambda:defaultdict(list))
    for e in projected:
        sid=e.get('source_quality',{}).get('evidence_source_id') or e['paper_id']
        by_pair[e['paper_id'],sid,e['a'],e['b']][e['effort_variant']].append(e)
    observations=[];multi=[]
    for (pid,sid,a,b),variants in sorted(by_pair.items()):
        masses=[];wins=[]
        for rows in variants.values():
            counts=Counter(e['benchmark_id'] for e in rows)
            ww=[weights[pid]/(len(rosters[pid,e['group_id']])-1)/(len(counts)*counts[e['benchmark_id']])**measurement_exponent
                * (measurement_factors.get(e['group_id'],1.) if measurement_factors is not None else 1.) for e in rows]
            for row,weight in zip(rows,ww):row['fit_weight']=weight/len(variants)
            masses.append(math.fsum(ww));wins.append(math.fsum(w*e['y'] for w,e in zip(ww,rows)))
        mass=math.fsum(masses)/len(masses)
        observations.append(dict(paper_id=pid,evidence_source_id=sid,a=a,b=b,y=math.fsum(wins)/math.fsum(masses),weight=mass))
        if len(variants)>1:multi.append(dict(paper_id=pid,a=a,b=b,configurations=len(variants),weight=mass))
    # A paper's many submetrics share a budget, including disjoint opponent sets.
    # Corroborated reprints share one source budget without dropping either paper.
    incident=defaultdict(lambda:defaultdict(float))
    source_papers=defaultdict(set)
    for r in observations:
        sid=r['evidence_source_id'];source_papers[sid].add(r['paper_id'])
        incident[sid][r['a']]+=r['weight'];incident[sid][r['b']]+=r['weight']
    factors={sid:min(1.,max(weights[p] for p in source_papers[sid])/max(masses.values()))
             for sid,masses in incident.items()}
    for r in observations:r['weight']*=factors[r['evidence_source_id']]
    for r in projected:r['fit_weight']*=factors[r.get('source_quality',{}).get('evidence_source_id') or r['paper_id']]
    model_sources=defaultdict(lambda:defaultdict(float))
    for r in observations:
        for node in (r['a'],r['b']):model_sources[node][r['evidence_source_id']]+=r['weight']
    concentration=[]
    for node,sources in sorted(model_sources.items()):
        total=math.fsum(sources.values())
        if total<=0:continue
        shares={sid:w/total for sid,w in sources.items()}
        dominant=max(shares,key=shares.get)
        concentration.append(dict(model=node[0],setting=node[1],independent_sources=len(sources),
            largest_source=dominant,largest_source_share=shares[dominant],
            effective_sources=1./math.fsum(v*v for v in shares.values())))
    before={e['paper_id']for e in edges};after={e['paper_id']for e in projected}
    audit=dict(policy='base-model-effort-pooling-v1',merged_models=sum(len(r['source_configurations'])>1 for r in registry),
        nodes_before=len(old_nodes),nodes_after=len(set(mapping.values())),papers_before=len(before),papers_after=len(after),
        source_comparisons=len(edges),cross_model_comparisons=len(projected),pooled_paper_pair_observations=len(observations),
        only_within_model_papers=sorted(before-after),self_comparisons=len(self_edges),
        registry=registry,within_model_comparisons=self_edges,multiple_configuration_pairs=multi,
        source_budget_factors=factors,
        source_concentration=concentration,
        likelihood='unchanged Bradley-Terry',weighting='mean metrics within benchmark; mean benchmarks and effort variants; source incident mass bounded by source quality weight',
        raw_sources_modified=False)
    return projected,observations,mapping,audit

def fit_observations(observations,nodes):
    import numpy as np
    from fit import BT
    ix={n:i for i,n in enumerate(nodes)};joined=defaultdict(lambda:[0.,0.])
    for r in observations:
        key=ix[r['a']],ix[r['b']];joined[key][0]+=r['weight'];joined[key][1]+=r['weight']*r['y']
    m=BT.__new__(BT);m.names=nodes;m.n=len(nodes);m.shrinkage=0.;m.alpha=0.
    m.a=np.array([k[0]for k in joined]);m.b=np.array([k[1]for k in joined]);mass=np.array([v[0]for v in joined.values()])
    m.w=mass/mass.sum();m.y=np.array([v[1]/v[0]for v in joined.values()])
    return m.fit()
