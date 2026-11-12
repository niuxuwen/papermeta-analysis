"""Check the data behind a fitted ranking and summarize direct paper evidence."""
from collections import Counter, defaultdict
from itertools import combinations
from math import isclose, isfinite
from statistics import mean


def validate_edges(records):
    seen = set()
    origins = {}
    for row in records:
        a, b = sorted((tuple(row['a']), tuple(row['b'])))
        group = row['group_id']
        origin = row['paper_id'], row['benchmark_id']
        if not group or not all(origin) or a == b or row['y'] not in (0, .5, 1):
            raise ValueError(f'Invalid source comparison in {group}')
        if origins.setdefault(group, origin) != origin:
            raise ValueError(f'Conflicting source identity for group {group}')
        key = group, a, b
        if key in seen:
            raise ValueError(f'Duplicate comparison in {group}: {a}, {b}')
        seen.add(key)


def assess(records, ranking, vendor, minimum_papers=5, review_minimum=3, score_key='basket_score_0_100'):
    nodes = [(row['model'], row['setting']) for row in ranking]
    scores = [row[score_key] for row in ranking]
    if len(set(nodes)) != len(nodes) or any(not isfinite(s) or (score_key == 'basket_score_0_100' and not 0 <= s <= 100) for s in scores):
        raise ValueError('Invalid model identity or basket score')
    if scores != sorted(scores, reverse=True):
        raise ValueError('Display order differs from fitted scores')
    papers = defaultdict(set)
    outcomes = defaultdict(lambda: defaultdict(list))
    for row in records:
        a, b = row['a'], row['b']
        paper = row['paper_id']
        papers[a].add(paper)
        papers[b].add(paper)
        pair = tuple(sorted((a, b)))
        outcomes[pair][paper].append(row['y'] if pair[0] == a else 1-row['y'])
    if set(nodes) != set(papers):
        raise ValueError('Fitted models differ from audited models')
    for node, row in zip(nodes, ranking):
        if len(papers[node]) != row['papers'] or row['papers'] < minimum_papers:
            raise ValueError(f'Incorrect paper coverage for {node}')
    model_vendors = {node: vendor(node) for node in nodes}
    summaries = defaultdict(Counter)
    reviews = []
    for upper, lower in combinations(range(len(nodes)), 2):
        a, b = nodes[upper], nodes[lower]
        maker = model_vendors[a]
        if not maker or maker != model_vendors[b] or a[0] == b[0]:
            continue
        pair = tuple(sorted((a, b)))
        votes = {p: mean(ys) if pair[0] == a else 1-mean(ys)
                 for p, ys in outcomes.get(pair, {}).items()}
        wins = sum(y > .5 for y in votes.values())
        losses = sum(y < .5 for y in votes.values())
        if len(votes) < review_minimum:
            status = 'sparse' if votes else 'no_direct_papers'
        elif isclose(scores[upper], scores[lower], abs_tol=1e-9) or wins == losses:
            status = 'tie'
        else:
            status = 'review' if losses > wins else 'aligned'
        summaries[maker][status] += 1
        if status == 'review':
            reviews.append(dict(vendor=maker, upper=a, lower=b, ahead=wins,
                                behind=losses, tied=len(votes)-wins-losses, papers=votes))
    return dict(review_minimum=review_minimum, vendors=summaries, reviews=reviews,
                unassigned_models=[node for node in nodes if not model_vendors[node]])
