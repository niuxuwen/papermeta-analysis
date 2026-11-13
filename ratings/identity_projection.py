"""Unify exact protected identities across review batches, before fitting.

Uses the repository's identity grammar, never fuzzy or score-based aliases.
Conflicting same-group outcomes block a proposed merge, not the whole paper.
"""
from collections import defaultdict
import re
from math import isclose
from model_dedup import identify

def project_edges(edges, references=()):
    nodes = sorted({tuple(e[k]) for e in edges for k in ('a','b')})
    parsed = {n: identify(*n) for n in nodes}
    # GPT-OSS is named by parameter scale rather than a separate version.
    # The shared grammar conservatively treats it as unversioned; only these
    # exact spelling variants can be safely joined here.
    for n in nodes:
        m = re.fullmatch(r'(?i)GPT[ -]+OSS[ -]+(20|120)B',n[0])
        if m:
            parsed[n] = {**parsed[n], 'key':('gpt-oss-scale',m[1],n[1]),
                         'name':'GPT-OSS '+m[1]+'B','setting':n[1]}
    clusters = defaultdict(list)
    for n in nodes:
        clusters[parsed[n]['key']].append(n)
    # Prefer complete, well-separated existing labels; never select by rating.
    def display_order(n):
        name = parsed[n]['name']
        return (name not in references,
                bool(re.search(r'(?i)^(?:gpt|claude|gemini|gemma|qwen|glm|grok|llama|internvl|deepseek|mimo|olmo|molmo)\d',name)),
                bool(re.match(r'(?i)^gpt',name)) and not name.startswith('GPT-'),
                name.count(' ') if name.startswith('GPT-') else 0,
                len(name),name.casefold(),name)
    targets = {}
    for key, members in clusters.items():
        chosen = min(members,key=display_order)
        targets[key] = (parsed[chosen]['name'], parsed[chosen]['setting'])
    blocked = set()
    conflicts = []
    grouped = defaultdict(list)
    for e in edges:
        grouped[e['paper_id'],e['group_id']].append(e)
    # A non-tie between proposed aliases proves they cannot be merged safely
    # with only these comparison artifacts. Keep those original identities.
    for group, records in grouped.items():
        outcomes = defaultdict(list)
        for e in records:
            ka,kb = (parsed[tuple(e[k])]['key'] for k in ('a','b'))
            a,b = targets[ka],targets[kb]
            if a==b and e['y']!=.5:
                blocked.add(ka)
                conflicts.append(dict(paper_id=group[0],group_id=group[1],reason='NON_TIE_BETWEEN_PROPOSED_ALIASES',source_nodes=[e['a'],e['b']]))
            elif a!=b:
                pair=(a,b) if a<b else (b,a)
                outcomes[pair].append((e['y'] if a<b else 1-e['y'],ka,kb))
        for pair, values in outcomes.items():
            if max(v[0] for v in values)-min(v[0] for v in values)>1e-12:
                for _,ka,kb in values:
                    if len(clusters[ka])>1:blocked.add(ka)
                    if len(clusters[kb])>1:blocked.add(kb)
                conflicts.append(dict(paper_id=group[0],group_id=group[1],reason='CONFLICTING_OUTCOMES_AFTER_ALIAS_MERGE',target_pair=pair))
    mapping = {n: n if parsed[n]['key'] in blocked else targets[parsed[n]['key']] for n in nodes}
    result=[];seen={};duplicates=[];self_pairs=[]
    for e in edges:
        a,b = mapping[tuple(e['a'])],mapping[tuple(e['b'])]
        if a==b:
            assert e['y']==.5
            self_pairs.append(dict(paper_id=e['paper_id'],group_id=e['group_id'],source_nodes=[e['a'],e['b']]))
            continue
        y=e['y']
        if a>b:a,b,y=b,a,1-y
        key=(e['paper_id'],e['group_id'],e['benchmark_id'],a,b,e.get('beta',1))
        if key in seen:
            assert isclose(seen[key],y,abs_tol=1e-12)
            duplicates.append(dict(paper_id=e['paper_id'],group_id=e['group_id'],pair=[a,b]))
            continue
        seen[key]=y
        result.append({**e,'a':a,'b':b,'y':y})
    registry=[dict(target=targets[key],source_nodes=members,status='REVIEW_CONFLICT' if key in blocked else 'EXACT_IDENTITY_MERGED') for key,members in clusters.items() if len(members)>1]
    audit=dict(policy='cross-batch-protected-identity-v1',nodes_before=len(nodes),
        nodes_after=len({e[k] for e in result for k in ('a','b')}),
        papers_before=len({e['paper_id'] for e in edges}),papers_after=len({e['paper_id'] for e in result}),
        comparisons_before=len(edges),comparisons_after=len(result),
        merged_clusters=sum(r['status']=='EXACT_IDENTITY_MERGED' for r in registry),
        registry=registry,conflicts=conflicts,duplicate_comparisons=duplicates,self_comparisons=self_pairs,
        scoring_formula_changed=False,raw_sources_modified=False)
    return result,mapping,audit
