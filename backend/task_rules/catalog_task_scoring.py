"""Task-related benchmark references from source-audited catalogue labels.

Catalogue relevance is not metric-level capability attribution. This path never
upgrades REVIEW annotations, infers protocol constraints or claims task success.
"""
from collections import defaultdict
from copy import deepcopy
import math
from datetime import datetime,timezone
from statistics import fmean
from .catalog_label_state import supported_label_ids
from .task_labels import validate_profile
from .task_reference_fit_v6 import fit_references
from .task_measurements import inspect, safe_scores, source_metadata, facet_labels, POLICY as ATTRIBUTION_POLICY
from .global_scoring import comparison_target
from .publication_quality import general_model_issue,metric_role
from .scoring_preparation import digest
from .relative_scoring import _benchmark
from .measurement_semantics import POLICY as MEASUREMENT_POLICY
from .task_measurement_policy import modality_matches,task_metric_role
from .task_constraints import unverified_protocol_fields

METHOD='catalog_task_pairwise_reference'
VERSION=11

def prepare_inputs(index, catalog, observations=None):
    fields=('group_id','paper_id','benchmark_id','benchmark_identity','table_id','row_key',
        'metric','metric_role_context','model_setting','comparison_key','direction','score_scale',
        'blocked_reasons','extraction_in_progress','records_fingerprint')
    groups=[{**{k:deepcopy(g[k]) for k in fields if k in g},
        'scores':[{k:deepcopy(s[k]) for k in ('model_canonical','value_numeric','observation_ids') if k in s}
                  for s in g['scores']]} for g in index.get('groups',[])]
    source_metadata(groups,observations)
    from .source_comparison_context import attach_source_context
    attach_source_context({'groups':groups},catalog,recover_tasks=False)
    models=[{k:deepcopy(m[k]) for k in ('model_canonical','model_setting','n_benchmarks','n_groups','coverage_pct') if k in m}
            for m in index.get('models',[])]
    benches=[]
    for b in catalog:
        raw=b.get('enrichment',{}).get('labels',{})
        labels={layer:sorted(supported_label_ids(raw,layer)) for layer in ('domains','tasks','modalities','capabilities')}
        if not labels['capabilities']:continue
        evidence=[{k:e.get(k) for k in ('layer','id','source_id','quote')} for e in raw.get('evidence',[])
            if isinstance(e,dict) and e.get('id') in labels.get(e.get('layer'),[]) and e.get('bound_to_benchmark') is True]
        benches.append({**{k:b[k] for k in ('paper_id','benchmark_id','benchmark_name','benchmark_identity','release_date','date_basis') if k in b},
            'catalog_labels':labels,'catalog_label_sources':deepcopy(b.get('catalog_label_sources',[])),
            'label_evidence':evidence})
    return {'groups':groups,'models':models,'exclusions':[]},benches

def score_task(index, catalog, profile, *, min_benchmarks=3, candidate_models=None, as_of=None):
    profile=validate_profile(profile)
    cap_weights={c['id']:c['weight'] for c in profile['capabilities']}
    total=math.fsum(cap_weights.values())
    cap_weights={k:v/total for k,v in cap_weights.items()}
    matched={};excluded=[]
    for b in catalog:
        labels=b['catalog_labels']
        caps=sorted(set(labels['capabilities'])&cap_weights.keys())
        if not caps:continue
        if profile['domains'] and not set(profile['domains'])&set(labels['domains']):continue
        constraints=profile['constraints']
        if not modality_matches(constraints['modality'],labels['modalities']):
            excluded.append({'reason':'input_modality_not_established','paper_id':b['paper_id'],'benchmark_id':b['benchmark_id']})
            continue
        # Catalogue tags do not establish language, retrieval or context budgets.
        pending=unverified_protocol_fields(constraints)
        matched[b['paper_id'],b['benchmark_id']]={**b,'matched_capabilities':caps,
            'relevance_weight':math.fsum(cap_weights[c] for c in caps),
            'unverified_constraints':pending,
            'exact_task_match':not pending and bool(set(profile['tasks'])&set(labels['tasks']))}
    from .source_comparison_context import resolved_role
    # Source facets keep exact-task and related evidence separate. Finding one
    # exact-task source must not remove other usable catalogue references.
    usable={(g['paper_id'],g['benchmark_id']) for g in index['groups']
            if not g.get('blocked_reasons') and not g.get('extraction_in_progress')
            and g.get('direction') in ('higher','lower')
            and task_metric_role(g)=='PERFORMANCE'
            and all(math.isfinite(s['value_numeric']) for s in g['scores'] if not general_model_issue(s['model_canonical']))
            and len([s for s in g['scores'] if not general_model_issue(s['model_canonical'])
                     and math.isfinite(s['value_numeric'])])>=2}
    match_scope='CAPABILITY_REFERENCE'
    related_count=len(matched)
    selected=[]
    for g in index['groups']:
        key=g['paper_id'],g['benchmark_id']
        if key not in matched:continue
        measurement=inspect(g,matched[key],profile)
        if task_metric_role(g)!='PERFORMANCE':
            excluded.append({'reason':measurement.get('reason')or'auxiliary_or_target_diagnostic','group_id':g['group_id'],'paper_id':g['paper_id'],'benchmark_id':g['benchmark_id']})
            continue
        from .task_measurements import condition_measurement
        measurement=condition_measurement(measurement,g)
        caps,basis,reason=measurement['capabilities'],measurement['basis'],measurement['reason']
        if not caps:
            excluded.append({'reason':reason,'paper_id':g['paper_id'],'benchmark_id':g['benchmark_id'],'group_id':g['group_id'],'metric':g['metric']})
            continue
        scores,bad=safe_scores(g,measurement)
        excluded.extend({'paper_id':g['paper_id'],'benchmark_id':g['benchmark_id'],'group_id':g['group_id'],'metric':g['metric'],**s}for s in bad)
        if len(scores)<2:
            excluded.append({'reason':'insufficient_source_valid_models','paper_id':g['paper_id'],'benchmark_id':g['benchmark_id'],'group_id':g['group_id']})
            continue
        pending=matched[key]['unverified_constraints']
        direct=not pending and basis=='SOURCE_SCOPED_TASK_OUTCOME' and bool(set(profile['tasks'])&set(measurement.get('tasks',[])))
        facet=('unverified_reference:' if pending else '')+measurement['facet']
        selected.append({**g,'scores':scores,'metric_capabilities':caps,'metric_attribution_basis':basis,'task_percentage':measurement.get('percentage',False),
                         'measurement_facet':facet,'unverified_constraints':pending,
                         'exact_task_match':direct,'evidence_kind':'UNVERIFIED_REFERENCE' if pending else 'DIRECT_TASK' if direct else 'RELATED_REFERENCE'})
    exact={(g['paper_id'],g['benchmark_id'])for g in selected
           if (g['paper_id'],g['benchmark_id'])in usable and g['exact_task_match']}
    if profile['tasks']:
        if exact:
            match_scope='SAME_TASK_AND_RELATED' if any(not g['exact_task_match']for g in selected)else 'SAME_TASK'
        else:match_scope='RELATED_CAPABILITIES_ONLY'
    for key,b in matched.items():b['exact_task_match']=any(g['exact_task_match']for g in selected if (g['paper_id'],g['benchmark_id'])==key)
    names={(s['model_canonical'],g['model_setting']) for g in selected for s in g['scores']}
    work={'groups':deepcopy(selected),'models':[deepcopy(m) for m in index['models']
        if (m['model_canonical'],m['model_setting']) in names],'exclusions':[]}
    fitted,fit_audit=fit_references(work,matched,as_of=as_of)
    # Selection only filters finished results; it never changes the reference fit.
    kept=None if candidate_models is None else set(candidate_models)
    models=[];panel=[];comparisons=[]
    ready=[g for g in work['groups'] if g.get('global_status')=='CORE_READY']
    model_groups=defaultdict(list)
    for g in ready:
        for s in g['scores']:
            key=(s['model_canonical'],g['model_setting'],g['measurement_facet'])
            if key in fitted:model_groups[key].append((g,s))
    reference_version=digest([METHOD,VERSION,sorted((g['group_id'],g['reference_profile']['reference_id']) for g in ready),
                              sorted((g['group_id'],g['metric_capabilities']) for g in ready),ATTRIBUTION_POLICY,
                              {k:fit_audit[k] for k in ('policy','neutral_prior_strength','task_coupling_strength','capability_residual_mix','temporal_scoring','common_source_calibration')}])[:24]
    def panel_id(setting,component):
        return 'task:'+digest([METHOD,VERSION,reference_version,setting,component,profile])[:24]
    required=defaultdict(set)
    for g in ready:
        b=matched[g['paper_id'],g['benchmark_id']]
        for cap in g['metric_capabilities']:required[g['model_setting'],cap,g['measurement_facet']].add(_benchmark(g))
        components={fitted[s['model_canonical'],g['model_setting'],g['measurement_facet']]['component']for s in g['scores']
                    if (s['model_canonical'],g['model_setting'],g['measurement_facet'])in fitted}
        for component in sorted(components):
            pid=panel_id(g['model_setting'],component)
            panel.append({**{k:g[k] for k in ('paper_id','benchmark_id','group_id','table_id','row_key','metric','model_setting')},
                'panel_id':pid,'capability_ids':g['metric_capabilities'],'score_scope':'BENCHMARK_TASK_REFERENCE',
                'benchmark_identity':_benchmark(g),
                'reference_models':[s['model_canonical'] for s in g['scores'] if not general_model_issue(s['model_canonical'])],
                'label_basis':g['metric_attribution_basis'],'measurement_facet':g['measurement_facet'],'task_relevance_weight':b['relevance_weight'],
                'exact_task_match':g['exact_task_match'],'evidence_kind':g['evidence_kind'],
                'unverified_constraints':g['unverified_constraints'],
                'evidence':b['label_evidence'][:2],'blocked_reasons':[]})
    for (name,setting,facet),records in sorted(model_groups.items()):
        m={'model_canonical':name,'model_setting':setting}
        if kept is not None and name not in kept:continue
        if not records:continue
        fit=fitted[name,setting,facet]
        setting=m['model_setting'];pid=panel_id(setting,fit['component'])
        entries=[]
        for g,s in records:
            others=[t for t in g['scores'] if t['model_canonical']!=s['model_canonical'] and not general_model_issue(t['model_canonical'])]
            entries.append({**{k:g[k] for k in ('group_id','paper_id','benchmark_id','table_id','metric','row_key','direction')},
                'benchmark_identity':_benchmark(g),'raw_value':s['value_numeric'],
                'comparison_target':fmean(comparison_target(g,s,t) for t in others),
                'observation_ids':s.get('observation_ids',[]),'measurement_facet':facet,'opponents':[t['model_canonical'] for t in others]})
        # One source comparison retains all matching capability IDs. Repeating
        # the same source/quote per capability bloats the all-abilities result.
        for c in entries:
            comparisons.append({'panel_id':pid,'score_scope':'BENCHMARK_TASK_REFERENCE',
                'group_id':c['group_id'],'benchmark_id':c['benchmark_id'],
                'capability_ids':next(g['metric_capabilities']for g,_ in records if g['group_id']==c['group_id']),
                'model_canonical':m['model_canonical'],'target_value':c['raw_value'],
                'reference_value':None,'reference_model':None,'outcome':None,
                'score':100*c['comparison_target'],'target_observation_ids':c['observation_ids']})
        abilities=[]
        for cap,weight in cap_weights.items():
            components=[c for c in entries if any(g['group_id']==c['group_id']and cap in g['metric_capabilities']for g,_ in records)]
            buckets=defaultdict(list)
            for c in components:
                buckets[c['benchmark_identity']].append(100*c['comparison_target'])
            denom=len(required[setting,cap,facet])
            observed_value=fmean(fmean(v) for v in buckets.values()) if buckets else None
            value=fit['capabilities'].get(cap) if buckets else None
            abilities.append({'capability_id':cap,'weight':weight,'score':None,'observed_score':value,
                'reference_score':value,'source_average':observed_value,'label_basis':('CATALOG_RELATED_REFERENCE' if facet.removeprefix('unverified_reference:').startswith('related_reference:') else 'SOURCE_SCOPED_TASK_OUTCOME'),'coverage':len(buckets)/denom if denom else 0,
                'n_benchmarks':len(buckets),'n_independent_benchmarks':len(buckets),'n_groups':len(components),
                'required_groups':sum(g['model_setting']==setting and g['measurement_facet']==facet and cap in g['metric_capabilities'] for g in ready),
                'status':'REFERENCE_AVAILABLE' if buckets else 'NO_EVIDENCE'})
        observed=[a for a in abilities if a['reference_score'] is not None]
        covered_weight=math.fsum(a['weight'] for a in observed)
        contribution=math.fsum(a['weight']*a['reference_score'] for a in observed)
        missing_weight=max(0.,1-covered_weight)
        score=contribution/covered_weight
        count=len({_benchmark(g) for g,_ in records})
        models.append({**{k:m[k] for k in ('model_canonical','model_setting')},
            'evidence_kind':records[0][0]['evidence_kind'],
            'task_eligible':all(g['exact_task_match']for g,_ in records) and not any(g['unverified_constraints']for g,_ in records),
            'unverified_constraints':sorted({k for g,_ in records for k in g['unverified_constraints']}),
            'source_papers':len({g['paper_id']for g,_ in records}),
            'evidence_level':('SINGLE_BENCHMARK_REFERENCE' if count==1 else 'MULTI_PAPER_COMPOSITE' if len({g['paper_id']for g,_ in records})>=2 else 'MULTI_BENCHMARK_REFERENCE'),
            'score_components':[{k:v for k,v in c.items() if k!='opponents'} for c in entries],
            'scored_benchmarks':count,'scored_groups':len(entries),
            'direct_opponents':len({n for c in entries for n in c['opponents']}),
            'measurement_facets':fit['measurement_facets'],'reference_methods':fit['reference_methods'],
            'panel_id':pid,'score_panel_id':pid,'score_version':pid,
            'score':score,'total_score':score,'publication_score':score,
            'publication_eligible':True,'publication_status':'REFERENCE_AVAILABLE',
            'status':'COMPLETE','provisional':False,'score_unit':'task_reference_0_100',
            'comparison_scope':'CALIBRATED_BENCHMARK_REFERENCES',
            'comparison_component':fit['component'],'reference_models':fit['reference_models'],
            'observed_reference_score':score,'estimated_weight':0.,'unmeasured_weight':missing_weight,
            'neutral_completion':None,'missing_capability_bounds':None,'measured_capability_ids':sorted(a['capability_id']for a in observed),
            'coverage':count/len({_benchmark(g) for g in ready if g['model_setting']==setting and g['measurement_facet']==facet}),
            'required_groups':sum(g['model_setting']==setting and g['measurement_facet']==facet for g in ready),
            'n_benchmarks':count,'n_groups':len(entries),'ability_scores':abilities,
            'capability_weight_coverage':covered_weight,
            'publication_reasons':[],
            'missing_reasons':[],'score_kind':'CONDITIONS_UNVERIFIED_REFERENCE' if any(g['unverified_constraints']for g,_ in records)else 'TASK_REFERENCE'})
    published=sum(m['publication_eligible'] for m in models)
    # Report every requested candidate, including a model with no matching row.
    # Keep this separate from fitted results; absence is never a zero score.
    overall=defaultdict(set);task_sources=defaultdict(set);task_groups=defaultdict(set)
    task_caps=defaultdict(set);by_name=defaultdict(list)
    for m in models:by_name[m['model_canonical']].append(m)
    for g in index['groups']:
        if (g.get('blocked_reasons') or g.get('extraction_in_progress')
            or g.get('direction') not in ('higher','lower')
            or task_metric_role(g)!='PERFORMANCE'):continue
        scores=[s for s in g['scores'] if not general_model_issue(s['model_canonical'])
            and math.isfinite(s['value_numeric'])]
        if len(scores)<2:continue
        for s in scores:overall[s['model_canonical']].add(_benchmark(g))
    for g in ready:
        b=matched[g['paper_id'],g['benchmark_id']]
        for s in g['scores']:
            name=s['model_canonical']
            if general_model_issue(name):continue
            task_sources[name].add(_benchmark(g));task_groups[name].add(g['group_id'])
            task_caps[name].update(g['metric_capabilities'])
    candidates=sorted(overall if kept is None else kept)
    candidate_audit=[]
    for name in candidates:
        rows=by_name[name];scored=[m for m in rows if m['publication_eligible']]
        count=len(task_sources[name]);state='SCORABLE' if scored else 'NO_TASK_EVIDENCE'
        candidate_audit.append({'model_canonical':name,'status':state,
            'task_eligible':any(m['task_eligible']for m in scored),
            'unverified_constraints':sorted({k for m in scored for k in m['unverified_constraints']}),
            'overall_benchmarks':len(overall[name]),'task_benchmarks':count,
            'task_groups':len(task_groups[name]),'matched_capabilities':sorted(task_caps[name]),
            'covered_capability_weight':math.fsum(cap_weights[c] for c in task_caps[name]),
            'required_benchmarks':1,
            'published_settings':sorted({m['model_setting'] for m in scored})})
    capability_coverage=[]
    for cap,weight in cap_weights.items():
        cap_groups=[g for g in ready if cap in g['metric_capabilities']]
        capability_coverage.append({'capability_id':cap,'weight':weight,
            'n_benchmarks':len({_benchmark(g) for g in cap_groups}),
            'n_groups':len(cap_groups),'n_models':len({s['model_canonical'] for g in cap_groups
                for s in g['scores'] if not general_model_issue(s['model_canonical'])}),
            'status':'MATCHED' if cap_groups else 'NO_MATCHING_BENCHMARK'})
    benchmark_matches=[]
    for source,b in matched.items():
        gs=[g for g in ready if (g['paper_id'],g['benchmark_id'])==source]
        if not gs:continue
        proof=[]
        for cap in sorted({c for g in gs for c in g['metric_capabilities']}):
            e=next((e for e in b['label_evidence'] if e['layer']=='capabilities' and e['id']==cap),None)
            if e:proof.append({**e,'quote':e['quote'][:800]})
        benchmark_matches.append({**{k:b[k] for k in ('paper_id','benchmark_id','benchmark_name')},
            'benchmark_identity':_benchmark(gs[0]),'matched_capabilities':sorted({c for g in gs for c in g['metric_capabilities']}),
            'domains':b['catalog_labels']['domains'],'tasks':b['catalog_labels']['tasks'],
            'exact_task_match':b['exact_task_match'],'relevance_weight':b['relevance_weight'],
            'evidence_kind':gs[0]['evidence_kind'],
            'unverified_constraints':b['unverified_constraints'],
            'groups':len(gs),'group_ids':[g['group_id'] for g in gs],
            'model_names':sorted({s['model_canonical'] for g in gs for s in g['scores']
                if not general_model_issue(s['model_canonical'])}),
            'metrics':sorted({g['metric'] for g in gs}),'evidence':proof})
    matched_count=len({(g['paper_id'],g['benchmark_id']) for g in ready})
    note='有一项相关成绩即可显示参考分。按具体任务类型与实验条件分别比较；单项评测使用固定同场参考，多项同类评测使用来源比较网络。缺测留空，不补分；不同组不混排。候选选择不改变分数。'
    if match_scope=='RELATED_CAPABILITIES_ONLY':
        note='暂无同类型任务的可用成绩；当前仅显示相近能力参考，不表示完成该任务的表现。'+note
    elif match_scope=='SAME_TASK_AND_RELATED':
        note='同类任务成绩与相关能力参考分别展示，相关参考不参与同类任务的评分。'+note
    if not published:
        note=(f'已匹配 {matched_count} 项相关 Benchmark；当前所选模型暂无相关成绩，可查看匹配来源或调整候选模型。'
              if matched_count else '当前没有满足任务能力、领域和已验证硬约束的相关 Benchmark；可按实际需要调整任务要求。')
    if unverified_protocol_fields(profile['constraints']) and published:
        note='当前来源尚未核实指定语言、知识访问或上下文条件；以下仅为条件待核的来源参考，不表示模型已满足任务要求。'
    return {'method':{'name':METHOD,'version':VERSION,'score_range':[0,100],
        'measurement_policy':MEASUREMENT_POLICY,'task_attribution_policy':ATTRIBUTION_POLICY,
        'capability_display_labels':{'code_correctness':'代码任务成果参考','domain_knowledge':'领域任务成果参考'},
        'measurement_facets':facet_labels(g['measurement_facet']for g in ready),
        'measurement_scope':'Final task performance only; source-defined prompt/intervention effects and statistical diagnostics remain raw evidence and never enter fitted capability references.',
        'minimum_related_benchmarks':1,
        'temporal_scoring':fit_audit['temporal_scoring'],
        'common_source_calibration':fit_audit['common_source_calibration'],
        'shared_comparison_policy':fit_audit['contrast_policy'],
        'score_formula':'Within each task facet, sum(weight * observed reference) / measured weight. Single-benchmark components use fixed empirical peers without neutral shrinkage; multi-benchmark components use independent comparison fitting. Never combine different facets into an overall order.',
        'missing_data':'One valid related measurement suffices. Missing values remain null, not 50 or 0. Measured capability masks define separate comparison cohorts. Numeric zero remains evidence.',
        'matching':'Keep all usable matched sources. Exact task outcomes and catalogue-related measurements have separate facets and never share a fitted score.',
        'candidate_selection':'Applied after fitting; candidate choices do not alter scores or reference models.'},
        'profile':deepcopy(profile),'match_scope':match_scope,'related_catalogue_count':related_count,
        'evidence_summary':{kind:{'benchmarks':len({_benchmark(g)for g in ready if g['evidence_kind']==kind}),
            'papers':len({g['paper_id']for g in ready if g['evidence_kind']==kind}),
            'models':len({m['model_canonical']for m in models if m['evidence_kind']==kind}),
            'panels':len({m['panel_id']for m in models if m['evidence_kind']==kind})}for kind in ('DIRECT_TASK','RELATED_REFERENCE','UNVERIFIED_REFERENCE')},
        'computed_at':datetime.now(timezone.utc).isoformat(),
        'available':bool(published),'status':'REFERENCE_READY' if published else 'INSUFFICIENT_MATCHED_EVIDENCE',
        'kind':'TASK_INDEX','models':models,'panel':panel,'comparisons':comparisons,'exclusions':excluded,
        'annotation_scope':'SOURCE_AUDITED_BENCHMARK_LABELS','label_basis':'BENCHMARK_LEVEL',
        'matched_benchmarks':matched_count,
        'matched_capabilities':sorted({cap for g in ready for cap in g['metric_capabilities']}),
        'candidate_audit':candidate_audit,'capability_coverage':capability_coverage,
        'benchmark_matches':benchmark_matches,
        'note':note,
        'validation':{'status':'BENCHMARK_REFERENCE_NOT_TASK_SUCCESS','note':'标签用于初筛，来源指标与子领域决定计分；任务成果参考不等同于独立认知能力测量，也不表示真实任务成功率。'},
        'source_normalization_audit':fit_audit}
