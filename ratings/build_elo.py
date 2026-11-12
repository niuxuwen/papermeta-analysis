"""Fit the local publication's Elo board on its own source comparisons."""
import gzip
import hashlib
import json
import sys
import math
from collections import Counter, defaultdict
from pathlib import Path
from dataclasses import dataclass

from fit import vendor, admissible, fitters, export
from rank_review import assess, validate_edges
from weighted_bt import pair_records, mutual_components
from publication_weights import time_factor, official_factor, composite
from model_dedup import project
from alias_projection import project_records
from source_quality import prepare_data, attach_provenance, filter_board_records

RULES = Path(__file__).resolve().parent
ROOT = RULES.parent
SITE = ROOT / 'site'
def load(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw)

@dataclass
class EloInputs:
    manifest: dict
    data: dict
    comparisons: list
    paper_weights: dict
    references: list
    registry: dict
    exclusions: dict
    default_papers: list


def load_elo_inputs():
    manifest = load(SITE / 'snapshot/current.json')
    item = manifest['task_inputs']
    raw = (SITE / item['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == item['sha256']
    reviewed, quality_audit = prepare_data(json.loads(gzip.decompress(raw)))
    data, _ = project(reviewed)
    source = load(Path(sys.argv[1]) / 'source.json.gz')
    assert source['snapshot_id'] == data['snapshot_id'] == manifest['snapshot_id']
    papers = {b['paper_id']: b for b in source['benchmarks']}
    del source

    tiers = {p['paper_id']:p for p in load(RULES / 'paper-weights.json')}
    official = load(RULES / 'official-source-registry.json')
    projections = data['measurements']['groups']
    groups = data['index']['groups']
    records, exclusions = pair_records(groups, projections=projections)
    identities = load(RULES / 'verified-alias-registry.json')['entries']
    registry = {(e['paper_id'],e['name'],e['setting']):e for e in identities}
    by_id = {g['group_id']:g for g in groups}
    # Configuration-specific aliases only apply to the original reviewed table.
    mapped = []
    for scoped in (False, True):
        scoped_tables = {(e['paper_id'],t['table_id']) for e in identities if e['configuration'] for t in e['scored_tables']}
        batch = [dict(r,q=1) for r in records if ((r['paper_id'],by_id[r['group_id']]['table_id']) in scoped_tables) == scoped]
        applicable = {k:v for k,v in registry.items() if not v['configuration'] or scoped}
        rows, _ = project_records(data,batch,applicable)
        mapped.extend(rows)
    weights = {}
    defaults = []
    for pid in {r['paper_id'] for r in mapped}:
        paper = papers[pid]
        previous = tiers.get(pid)
        if previous and previous['arxiv_id'] == paper['arxiv_id']:
            tier = previous['source_weight']
        else:
            tier = .4
            defaults.append(pid)
        weights[pid] = composite(tier,time_factor(paper['paper_first_published'],data['generated_at']),
                                 official_factor(paper,official)[0])
    for r in mapped:
        r['a'], r['b'] = tuple(r['a']), tuple(r['b'])
    mapped = attach_provenance(mapped, groups)
    exclusions['source_quality_audit'] = quality_audit
    validate_edges(mapped)
    refs = load(RULES/'references.json')
    return EloInputs(manifest, data, mapped, weights, refs, registry, exclusions, defaults)


def fit_main_elo(records, weights, *, min_papers=5, quality_board='Main'):
    records, _ = filter_board_records(records, board=quality_board)
    eligible, nodes, _ = admissible(records, min_papers, mutual_components)
    fit = fitters(eligible, nodes, weights)('paper-half') if eligible else None
    return eligible, nodes, fit


def main():
    inputs = load_elo_inputs()
    data, weights, refs = inputs.data, inputs.paper_weights, inputs.references
    groups = data['index']['groups']
    by_id = {g['group_id']: g for g in groups}
    registry, defaults, exclusions = inputs.registry, inputs.default_papers, inputs.exclusions
    item = inputs.manifest['task_inputs']
    eligible, nodes, fit = fit_main_elo(inputs.comparisons, weights)
    ranking = export(fit,eligible,refs)
    audit = assess(eligible,ranking,vendor)
    node_ids = {node:i for i,node in enumerate(nodes)}
    group_nodes = defaultdict(set)
    repeats = Counter()
    for edge in eligible:
        pair = tuple(sorted((edge['a'],edge['b'])))
        group_nodes[edge['group_id']].update(pair)
        repeats[edge['paper_id'],pair] += 1
    group_ids = {gid:i for i,gid in enumerate(sorted(group_nodes))}
    sources = dict(snapshot_id=data['snapshot_id'],nodes=nodes,
        groups=[[gid,by_id[gid]['paper_id'],by_id[gid]['table_id'],by_id[gid]['benchmark_id'],by_id[gid]['metric']]
                for gid in group_ids], pairs=[])
    for edge in eligible:
        a,b = edge['a'],edge['b']
        gid,pid = edge['group_id'],edge['paper_id']
        weight = weights[pid]/(len(group_nodes[gid])-1)/math.sqrt(repeats[pid,tuple(sorted((a,b)))])
        sources['pairs'].append([group_ids[gid],node_ids[a],node_ids[b],edge['y'],weight])
    packed=gzip.compress(json.dumps(sources,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    proof_path='snapshot/'+inputs.manifest['snapshot_id']+'/elo-pairs-'+hashlib.sha256(packed).hexdigest()[:16]+'.json.gz'
    (SITE/proof_path).write_bytes(packed)
    source_names = defaultdict(Counter)
    for g in groups:
        for s in g['scores']:
            model = s['model_canonical']
            entry = registry.get((g['paper_id'],model,g.get('model_setting','')))
            if entry and not entry['configuration']:
                model = entry['canonical_name']
            node = model,s.get('dedup_condition','')
            source_names[node][s['dedup_original_model_name'],s['dedup_original_model_setting']] += 1
    for row in ranking:
        node = row['model'],row['setting']
        row['source_names'] = [list(pair) for pair,count in source_names[node].most_common()]
    payload = dict(snapshot_id=data['snapshot_id'], task_inputs_sha256=item['sha256'], references=refs,
                   papers=len({r['paper_id'] for r in eligible}), comparisons=len(eligible),
                   models=ranking, reviews=audit['reviews'], pair_source=proof_path, source_tier_default_papers=sorted(defaults),
                   exclusions=exclusions, source_quality_policy=data.get('source_quality_policy'),
                   source_quality_overlap_audit=filter_board_records(inputs.comparisons)[1])
    output = SITE/'snapshot-elo-data.js'
    temp = output.with_suffix('.tmp')
    temp.write_text('window.snapshotElo = '+json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False)+';',encoding='utf8')
    temp.replace(output)

    print(data['snapshot_id'],len(nodes),payload['papers'],len(eligible),'default tier papers',len(defaults))
    print([(r['model'],round(r['basket_score_0_100'],2)) for r in ranking[:6]])

if __name__ == '__main__':
    main()
