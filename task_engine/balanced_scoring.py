from __future__ import annotations

from collections import Counter, defaultdict

from .publication_quality import general_model_issue

from .relative_scoring import _benchmark

MIN_BENCHMARKS = 3

MIN_SOURCE_PAPERS = 1

def comparison_core(groups, minimum=MIN_BENCHMARKS, min_papers=MIN_SOURCE_PAPERS):
    """Bipartite peeling; no outcome, name age, vendor or displayed selection.

    A remaining contest has >=2 eligible general models. Each remaining model
    must have >=minimum independent benchmark identities and >=min_papers
    distinct source papers in those contests. A sparse opponent cannot qualify
    another model for broad publication merely by providing an indirect bridge.
    The original source groups/scores are never removed or rewritten.
    """
    current = [{**g, 'scores':[s for s in g['scores'] if not general_model_issue(s['model_canonical'])]}
               for g in groups]
    current = [g for g in current if len(g['scores'])>=2]
    rounds = 0
    while True:
        benches, papers = defaultdict(set), defaultdict(set)
        for g in current:
            for s in g['scores']:
                benches[s['model_canonical']].add(_benchmark(g))
                papers[s['model_canonical']].add(g['paper_id'])
        names = {n for n in benches if len(benches[n])>=minimum and len(papers[n])>=min_papers}
        updated = [{**g,'scores':[s for s in g['scores'] if s['model_canonical'] in names]} for g in current]
        updated = [g for g in updated if len(g['scores'])>=2]
        rounds += 1
        if sum(len(g['scores']) for g in updated)==sum(len(g['scores']) for g in current):
            return updated, dict(rounds=rounds, models=sorted(names), min_benchmarks=minimum, min_source_papers=min_papers)
        current = updated

def source_weights(groups):
    """Each model has incident paper and benchmark pair weight <=1.

    Each paper/benchmark incidence gets 1/max(paper benchmark degree,
    benchmark paper degree), then divides across source groups and
    opponents. Thus more columns, opponents, named subsets or duplicate
    publications cannot give one model unbounded fitting weight from a single
    paper or benchmark. A paper's total weight still grows with distinct
    tested models; it is NOT one independent source per pair or column.
    """
    pb, bp = defaultdict(set), defaultdict(set)
    count = Counter((g['paper_id'],_benchmark(g)) for g in groups)
    for g in groups:
        pb[g['paper_id']].add(_benchmark(g)); bp[_benchmark(g)].add(g['paper_id'])
    return {g['group_id']:1/(max(len(pb[g['paper_id']]),len(bp[_benchmark(g)]))
            *count[g['paper_id'],_benchmark(g)]*(len(g['scores'])-1)) for g in groups}
