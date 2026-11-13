"""Build the four local capability boards from the frozen publication's comparison evidence."""
import gzip
import json
import re
import subprocess
from collections import defaultdict

import math
from build_elo import SITE, fit_main_elo, load_elo_inputs, export, coverage_audit, SCORING_REVISION
from common_basket import calibrate, METHOD
from soft_outcomes import METHOD as OUTCOME_METHOD

MIN_CATEGORY_PAPERS = 5

def add_category_scores(rows, panel=None):
    return calibrate(rows, panel=panel)

# Explicit task labels describe what was assessed. Skills like reading or
# following instructions are also used inside specialist tasks.
GENERAL_TASKS = {'writing', 'summarization', 'translation', 'dialogue', 'reading_comprehension'}
MATH_SKILLS = {'mathematical_reasoning', 'statistical_reasoning'}
AGENT_SKILLS = {'interactive_execution', 'tool_use', 'planning'}
AGENT_TASKS = {'interactive_execution', 'tool_workflow', 'planning'}
CODE_METRIC = re.compile(r'\b(?:compilation|compiles?|unit tests?|code coverage|patch correctness|program state|test pass rate)\b', re.I)
SCIENCE_METRIC = re.compile(r'\b(?:reaction yield|molecular propert(?:y|ies)|protein structure|physical mechanism|theorem proving)\b', re.I)

# Reviewed source tables. Only the named outcomes are covered, including
# tables that lack task annotations. Other columns use the normal rules.
REVIEWED_OUTCOMES = {
    # These scores combine tasks or measure an end product. A component skill
    # mentioned in the paper does not turn the combined score into a skill test.
    'bench-3d00e4c984ba36c6': {'Agent': r'Clean|(?:Easy|Medium|Hard) drift|Hard IDG'},  # GENERAL-TEST intent handling
    'bench-3af627bf886a479c': {'Agent': r'Task avg\.|Macro avg\.'},  # BlenderWorld 3D creation by agents
    'bench-10d7677979755c3a': {'Agent': r'3-Seed Mean ± SE'},  # SpaceAct closed-loop action
    'bench-4a5c9d489d4c762f': {'Agent': r'Ind\.'},  # OfficeTown industrial deliverables
    'bench-683ac732010bba90': {'Agent': r'SWE strict passes / 30|ToolChoice strict passes / 10',
                              'Coding': r'SWE strict passes / 30'},  # two distinct task sets in Table 11
    'bench-d3c53c81f89e6b32': {'General': r'(?:VE|TQ|AQ|MS|L-TVA|G-TVA)↑'},  # rendered video quality
    'bench-08493c61984806bb': {'Coding': r'ARCS EX \(%\)|EX(?:disambiguated|e2e) \(%\)'},  # ARCS SQL execution
    'bench-10bf027c8b9a6209': {'Coding': r'Endpoint@Acc|Method@Acc|Host@Acc|ParamF1|Mock|Robust'},  # SCCGBench
    'bench-156a95b58fabeb5c': {'Coding': r'(?:Arity|Exact Match) F1 \(%\)'},  # Build2SPARQL
    'bench-1c869b298b00e410': {'Science': r'Acc\. .*20%.*', 'Coding': r'Compile|No Errors|CodeBLEU'},  # PhySimCode
    'bench-22379390db3f0bde': {'Coding': r'Pass@1\(%\)'},  # AlgoREval
    'bench-284ca54d32115a6a': {'Coding': r'SpecMatch'},  # MintEval executable strategy
    'bench-3d5a1c46d6c88a8d': {'Coding': r'[123]|Pooled'},  # PLCWorld generated-program success
    'bench-44b81bd25215b916': {'Coding': r'Executability ↑'},  # ExeWorldBench
    'bench-61e8d59fd0c630aa': {'Coding': r'Build Err\. % ↓|Runtime Err\. % ↓|Failed tests'},  # EvoWeb
    'bench-72f4c19f019d47f2': {'Coding': r'pass@[15]'},  # HLS program repair
    'bench-884604e0ddc6bfc0': {'Coding': r'Pass rate'},  # DivAlgo
    'bench-8a6a9a0ece290b53': {'Coding': r'Recall'},  # CRBugBench bug detection (exclude cost)
    'bench-976805289044862c': {'Coding': r'Exact Match|Pass@1|BC \(Pass@1\)|SMG-[RM]'},  # VHDL-REPOBENCH
    'bench-a1ee6c64aa148d3a': {'Coding': r'Correct|Acc\.'},  # source-code tracing accuracy
    'bench-d71ed76091457ecf': {'Coding': r'(?:M|S)\d+ (?:Program State|Exceptions|(?:Inter|Intra)-procedural CFG|Invariants)|Overall|Telegram-bot|Python-control'},  # SWE-Flux
    'bench-d75aeebc4576327e': {'Coding': r'TQS'},  # quality of generated quantum tests
    'bench-ed004364473235e5': {'Coding': r'pass@1|Partial repair|Full repair|Patch generation'},  # TangleEval
}

# Repeated publication of the same measurement in an expanded roster.
# Remove only matching model pairs present in the primary table.
REPEATED_GROUPS = {
    '0e4ca58999472650f19ec07f': 'a200c05d692b90acaf9ba5f3',  # AgentIdeaBench Static
    'acb2965a49d033ea2ffbc3c4': 'ea8cd6949edfd42c1b05021b',  # CellTrack-Bench Repair F1
}

def comparison_key(record):
    a, b = record['a'], record['b']
    return (a, b, record['y']) if a < b else (b, a, 1 - record['y'])

def measurement_categories(group, label, tags, reviewed_code, owners):
    quality = group.get('source_quality', {})
    if not quality.get('eligible', True):
        return set()
    if quality.get('categories') is not None:
        return set(quality['categories'])
    if 'reviewed_categories' in group:
        return set(group['reviewed_categories'])
    metric = group['metric'].strip()
    if label is not None and not label.get('capabilities'):
        return set()
    reviewed = {category for category, pattern in REVIEWED_OUTCOMES.get(group['benchmark_id'], {}).items()
                if re.fullmatch(pattern, metric, re.I)}
    if reviewed:
        return reviewed
    if group['benchmark_id'] == 'bench-d3c53c81f89e6b32' and metric == 'Rank↓':
        return set()  # Average rank of the same video metrics, not another outcome.
    if label is None:
        return set()
    if re.search(r'(?:\bcost(?:/run)?\b|runtime \(min\)|output tokens|\$/)', metric, re.I):
        return set()
    skills = set(label.get('capabilities', []))
    if not skills:
        return set()
    facet = label.get('facet') or ''
    specific = bool(facet and not facet.startswith('related_reference:'))
    context = label if specific else tags
    domains = set(context.get('domains', []))
    tasks = set(context.get('tasks', []))
    classes = set()
    # Benchmark-level labels are usable for a focused subject. Mixed-domain
    # benchmarks need metric-specific evidence for a specialist attribution.
    focused = len(domains - {'general'}) <= 1
    if ('science' in domains and (focused or specific)
            or 'mathematical_problem_solving' in tasks and (focused or specific)
            or skills & MATH_SKILLS and (specific or not domains or domains <= {'science', 'education', 'general'})
            or SCIENCE_METRIC.search(metric)):
        classes.add('Science')
    code_skill = any(owners.get(skill) == 'Coding' for skill in skills)
    if ((code_skill or 'code_development' in tasks) and (specific or focused and domains <= {'software','general'})
            or not specific and reviewed_code or CODE_METRIC.search(metric)):
        classes.add('Coding')
    if tasks & AGENT_TASKS or skills & AGENT_SKILLS:
        classes.add('Agent')
    # Keep general-purpose outcomes, including standalone retrieval and
    # document synthesis. Reading a physics question alone is not a General result.
    if tasks & GENERAL_TASKS or not classes:
        classes.add('General')
    return classes

def category_evidence(inputs):
    manifest = inputs.manifest
    task = inputs.data
    catalog = json.loads(gzip.decompress((SITE / manifest['ranking']['path']).read_bytes()))
    assert catalog['snapshot_id'] == task['snapshot_id'] == manifest['snapshot_id']
    parents = json.loads(subprocess.check_output(['node', '-e',
        "console.log(JSON.stringify(require('./radar-viz.js').capabilityCategories))"], cwd=SITE))
    owner = {leaf: category for category, leaves in parents.items() for leaf in leaves}
    by_source = {(b['paper_id'], b['benchmark_id']): b for b in catalog['benchmarks'] if b['eligibility'] == 'ELIGIBLE'}
    tags_by_source = {(b['paper_id'], b['benchmark_id']): b['catalog_labels'] for b in task['catalog']}
    keys = list(by_source)
    reviewed = json.loads(subprocess.check_output(['node', '-e',
        "const keys=JSON.parse(require('fs').readFileSync(0,'utf8'));"
        "const viz=require('./radar-viz.js');"
        "console.log(JSON.stringify(keys.map(([paper_id,benchmark_id])=>"
        "Boolean(viz.catalogCodingEvidence({paper_id,benchmark_id})))));"],
        input=json.dumps(keys).encode(), cwd=SITE))
    reviewed_code = {key for key, verified in zip(keys, reviewed, strict=True) if verified}
    scoped = {}
    bench_indices, benchmarks, group_bench = {}, [], {}
    for group in task['index']['groups']:
        gid, pid, bid, metric = (group[k] for k in ('group_id','paper_id','benchmark_id','metric'))
        bench = by_source.get((pid, bid))
        source_url = ''
        if bench is None and group.get('reviewed_evidence_version'):
            bench = dict(paper_id=pid,benchmark_id=bid,benchmark_name=bid)
            source_url = group.get('reviewed_source_url','')
        label = task['measurements']['groups'].get(gid)
        if not bench:
            continue
        key = (pid, bid)
        tags = tags_by_source.get(key, bench.get('catalog_display_tags') or {})
        cats = measurement_categories(group, label, tags, key in reviewed_code, owner)
        if not cats:
            continue
        identity = bench.get('directory_identity') or (pid, bid)
        if identity not in bench_indices:
            bench_indices[identity] = len(benchmarks)
            benchmarks.append([bench['benchmark_name'], pid, bid, source_url])
        group_bench[gid] = bench_indices[identity]
        scoped[gid] = cats
    edges = defaultdict(list)
    primary_pairs = {gid: set() for gid in REPEATED_GROUPS.values()}
    for record in inputs.comparisons:
        gid = record['group_id']
        if gid in primary_pairs:
            primary_pairs[gid].add(comparison_key(record))
    for record in inputs.comparisons:
        gid = record['group_id']
        primary = REPEATED_GROUPS.get(gid)
        for category in scoped.get(gid, ()):
            if primary and category in scoped.get(primary, ()) and comparison_key(record) in primary_pairs[primary]:
                continue
            edges[category].append(record)
    return parents, edges, benchmarks, group_bench


def main():
    inputs = load_elo_inputs()
    manifest = inputs.manifest
    parents, edges, benchmarks, group_bench = category_evidence(inputs)
    boards, status = {}, {}
    for category in parents:
        eligible, nodes, fit = fit_main_elo(edges[category], inputs.paper_weights, min_papers=MIN_CATEGORY_PAPERS, quality_board=category)
        sources = defaultdict(set)
        papers = defaultdict(set)
        for record in eligible:
            for node in (record['a'], record['b']):
                sources[node].add(group_bench[record['group_id']])
                papers[node].add(record['paper_id'])
        rows = []
        for node in nodes:
            strength = fit['theta'][node]
            rows.append(dict(model=node[0], setting=node[1], elo=1000 + 400 * strength / math.log(10),
                             papers=len(papers[node]),
                             sources=sorted(sources[node], key=lambda idx: benchmarks[idx][0].casefold())))
        basket_audit = add_category_scores(rows)
        boards[category] = sorted(rows, key=lambda row: (-row['elo'], row['model'], row['setting']))
        status[category] = dict(min_papers=MIN_CATEGORY_PAPERS, score_unit='elo', basket=basket_audit,
                                coverage_audit=coverage_audit(edges[category], eligible, board=category),
                                available_benchmarks=len({group_bench[e['group_id']] for e in edges[category]}))
        print(category, len(rows), 'raw Elo')
    result = dict(scoring_revision=SCORING_REVISION, reviewed_evidence=inputs.data.get('reviewed_evidence_audit'), snapshot=manifest['snapshot_id'], benchmarks=benchmarks, boards=boards,
                  status=status, references=basket_audit['references'], outcome_method=OUTCOME_METHOD, score_unit='elo', method='main-batch-elo',
                  score_method=METHOD, source_quality_policy=inputs.data.get('source_quality_policy'),
                  coverage_policy='coverage-display-only-v1', display_min_papers=MIN_CATEGORY_PAPERS)
    output = SITE / 'capability-rankings.json'
    temp = output.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf8')
    temp.replace(output)


if __name__ == '__main__':
    main()
