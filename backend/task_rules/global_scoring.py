"""Global opponent-adjusted scores from source-gated same-condition contests."""
from collections import Counter, defaultdict
from itertools import combinations
import math
from statistics import fmean, pstdev
from .paired_scoring import components, fit, sigmoid, uncertainty
from .relative_scoring import _benchmark
from .scoring_preparation import digest
from .publication_quality import metric_role, general_model_issue, VERSION as QUALITY_POLICY
from .balanced_scoring import comparison_core, source_weights, MIN_BENCHMARKS, MIN_SOURCE_PAPERS
from .shared_task_scoring import graph, fit_graph, COUPLING_STRENGTH
from .source_consensus import source_pair_weights, pair_weight
from .temporal_scoring import attach_recency, HALF_LIFE_DAYS
from .measurement_semantics import describe_group, POLICY as MEASUREMENT_POLICY
from .neutral_prior_calibration import CALIBRATION
from .source_balanced_scoring import incident_source_weights, POLICY as SOURCE_BUDGET_POLICY
from .scoring_calibration_v112 import CALIBRATION as SOURCE_CALIBRATION
from .vendor_consistency import attach_paper_identities
from .source_comparison_context import attach_source_context,global_condition_exclusion,POLICY as SOURCE_CONTEXT_POLICY
from .common_source_calibration import attach as attach_common_calibration, cluster_gradients, CALIBRATION as COMMON_CALIBRATION

POLICY = 'vendor-blind-source-calibrated-composite-v16'
PRIOR_STRENGTH = CALIBRATION['selected_prior']
GLOBAL_COUPLING_STRENGTH = SOURCE_CALIBRATION['selected_coupling']
UNCERTAINTY_POLICY = 'calibrated-paper-family-working-interval-baseline-floor-v4'
MARGIN_TEMPERATURE = 1.0


def display_score(strength):
    return 100*sigmoid(strength)


def comparison_target(group, first, second):
    """Continuous, dimensionless same-condition contrast, not an item vote.

    This is an empirical relative scale, not a verified 0--100 source range or
    a significance test. With only two references its magnitude is necessarily
    uninformative about absolute practical importance.
    """
    ref=group['reference_profile']
    if ref.get('contrast_method')=='TWO_MODEL_ORDINAL_ONLY':
        delta=(first['value_numeric']-second['value_numeric'])*(1 if group['direction']=='higher' else -1)
        return .5 if delta==0 else .75 if delta>0 else .25
    sd=ref.get('contrast_scale',ref['standard_deviation'])
    if not sd:
        return .5
    a,b=first['value_numeric'],second['value_numeric']
    scale=max(abs(a),abs(b),sd) or 1.0
    delta=((a/scale)-(b/scale))/(sd/scale)
    return sigmoid((1 if group['direction']=='higher' else -1)*delta/MARGIN_TEMPERATURE)


def prepare_contests(index, *, scope='global'):
    counts,by_setting = Counter(),defaultdict(list)
    for g in index['groups']:
        g.pop('reference_profile',None)
        g.pop('global_pair_weights',None)
        g['global_reference_models'] = []
        g['global_pair_weight'] = None
        g['global_status'] = 'OUTSIDE_BROAD_COVERAGE_CORE'
        for s in g['scores']:
            s.pop('relative_score',None)
            s.pop('pairwise_score',None)
            s.pop('comparison_target',None)
        reason = None
        describe_group(g)
        from .task_measurement_policy import task_metric_role
        g['metric_role']=task_metric_role(g)
        if g['metric_role'] != 'PERFORMANCE':
            reason = 'non_capability_metric:' + g['metric_role']
        elif scope=='global' and global_condition_exclusion(g):
            reason = global_condition_exclusion(g)
        elif g.get('blocked_reasons') or g.get('extraction_in_progress'):
            reason = 'blocked_or_incomplete_source_group'
        elif len([s for s in g['scores'] if not general_model_issue(s['model_canonical'])])<2:
            reason = 'insufficient_reference_models'
        elif g.get('direction') not in ('higher','lower'):
            reason = 'unknown_direction'
        else:
            ordered = sorted((s for s in g['scores'] if not general_model_issue(s['model_canonical'])),key=lambda s:s['model_canonical'])
            values = [s['value_numeric'] for s in ordered]
            if not all(math.isfinite(v) for v in values):
                reason = 'nonfinite_source_values'
            else:
                scale = max(map(abs,values)) or 1.0
                reduced = [v/scale for v in values]
                reduced_mean,reduced_sd = fmean(reduced),pstdev(reduced)
                mean,sd = reduced_mean*scale,reduced_sd*scale
                ref = digest([POLICY,g['group_id'],[(s['model_canonical'],s['value_numeric'],s.get('observation_ids',[])) for s in ordered]])[:24]
                g['reference_profile'] = dict(policy=POLICY,reference_id=ref,reference_count=len(values),mean=mean,
                    reference_models=[s['model_canonical'] for s in ordered],
                    standard_deviation=sd,ddof=0,direction=g['direction'],records_fingerprint=g.get('records_fingerprint'))
                sign = 1 if g['direction']=='higher' else -1
                for s in ordered:
                    s['relative_score'] = sign*(s['value_numeric']/scale-reduced_mean)/reduced_sd if reduced_sd else 0
                    outcomes = [1 if sign*(s['value_numeric']-t['value_numeric'])>0 else .5 if s['value_numeric']==t['value_numeric'] else 0
                                for t in ordered if t['model_canonical']!=s['model_canonical']]
                    s['pairwise_score'] = 100*fmean(outcomes)
                    s['comparison_target'] = fmean(comparison_target(g,s,t) for t in ordered if t is not s)
                by_setting[g['model_setting']].append(g)
        g['relative_status'] = reason or 'READY'
        counts[g['relative_status']] += 1
    from .task_balanced_scoring import prepare_contrast_scales
    for groups in by_setting.values(): prepare_contrast_scales(groups)
    return by_setting,dict(counts)


def apply_global_scores(index, *, min_benchmarks=3, prior_strength=PRIOR_STRENGTH, benchmark_catalog=None,
                        group_relevance=None, compute_uncertainty=True, as_of=None,
                        half_life_days=HALF_LIFE_DAYS):
    if not math.isfinite(prior_strength) or prior_strength<=0:
        raise ValueError('Invalid neutral prior strength')
    minimum = max(MIN_BENCHMARKS,min_benchmarks)
    from .task_balanced_scoring import attach_task_strata, task_weights
    attach_task_strata(index, benchmark_catalog)
    source_context = attach_source_context(index, benchmark_catalog)
    attach_paper_identities(index['groups'],benchmark_catalog)
    temporal = attach_recency(index, benchmark_catalog, as_of=as_of, half_life_days=half_life_days)
    by_setting,counts = prepare_contests(index)
    references = sorted((g['group_id'],g['reference_profile']['reference_id']) for gs in by_setting.values() for g in gs)
    task_inputs=sorted((g['group_id'],g['task_balance_labels'],g['task_balance_strata'],g.get('task_budget_strata'),g.get('task_balance_recovery'),g.get('source_condition_key')) for g in index['groups'])
    temporal_inputs=sorted((g['group_id'],g['temporal_weight'],g['temporal_provenance']) for g in index['groups'])
    version_inputs = [POLICY,COMMON_CALIBRATION,SOURCE_BUDGET_POLICY,UNCERTAINTY_POLICY,SOURCE_CONTEXT_POLICY,digest(source_context),minimum,MIN_SOURCE_PAPERS,prior_strength,GLOBAL_COUPLING_STRENGTH,MARGIN_TEMPERATURE,references,task_inputs,temporal,temporal_inputs]
    if group_relevance is not None:
        if any(not math.isfinite(v) or not 0 < v <= 1 for v in group_relevance.values()):
            raise ValueError('Task relevance weights must be in (0,1]')
        version_inputs.append(sorted(group_relevance.items()))
    version = digest(version_inputs)[:24]
    summaries = []
    for setting in sorted({m['model_setting'] for m in index['models']}):
        available = sorted(by_setting.get(setting,[]),key=lambda g:g['group_id'])
        available_sources,available_papers = defaultdict(set),defaultdict(set)
        for g in available:
            for s in g['scores']:
                if not general_model_issue(s['model_canonical']):
                    available_sources[s['model_canonical']].add(_benchmark(g))
                    available_papers[s['model_canonical']].add(g['paper_id'])
        core_groups,core_audit = comparison_core(available,minimum,MIN_SOURCE_PAPERS)
        core_names = set(core_audit['models'])
        core_benchmarks,core_papers = defaultdict(set),defaultdict(set)
        for g in core_groups:
            for s in g['scores']:
                core_benchmarks[s['model_canonical']].add(_benchmark(g))
                core_papers[s['model_canonical']].add(g['paper_id'])
        # Narrow models supply valid observed opponent information, but cannot
        # receive a broad score or move its reference center merely by joining.
        groups = [{**g,'scores':[s for s in g['scores'] if not general_model_issue(s['model_canonical'])]} for g in available]
        weights, task_audit = task_weights(groups, source_weights(groups))
        weights = incident_source_weights(groups, weights)
        if group_relevance is not None:
            from .source_consensus import PairWeights
            old_mass = math.fsum(weights.pairs.values())
            pairs = {key:w*group_relevance[key[0]] for key,w in weights.pairs.items()}
            relevance_factor = math.fsum(pairs.values())/old_mass if old_mass else 1.
            weights = PairWeights({gid:w*group_relevance[gid] for gid,w in weights.items()}, pairs,
                dict(weights.audit,task_relevance_factor=relevance_factor,
                     new_total_mass=math.fsum(pairs.values())))
            # Preserve the neutral penalty relative to available evidence mass.
            task_audit['prior_factor'] *= relevance_factor
        fit_prior = prior_strength*task_audit['prior_factor']
        originals = {g['group_id']:g for g in available}
        for g in groups:
            original = originals[g['group_id']]
            original['global_reference_models'] = sorted(s['model_canonical'] for s in g['scores'])
            original['global_pair_weight'] = weights[g['group_id']]
            original['global_pair_weights'] = [[a['model_canonical'],b['model_canonical'],
                pair_weight(weights,g['group_id'],a['model_canonical'],b['model_canonical'])]
                for a,b in combinations(sorted(g['scores'],key=lambda s:s['model_canonical']),2)]
            original['task_balance_factor'] = g['task_balance_factor']
            original['global_status'] = 'CORE_READY'
        benchmark_counts = Counter(_benchmark(g) for g in groups)
        sources,opponents = defaultdict(lambda:defaultdict(list)),defaultdict(set)
        contests,per_benchmark = [],defaultdict(list)
        for g in groups:
            ordered = sorted(g['scores'],key=lambda s:s['model_canonical'])
            benchmark = _benchmark(g)
            weight = weights[g['group_id']]
            for s in ordered:
                sources[s['model_canonical']][benchmark].append((g,s))
                opponents[s['model_canonical']].update(t['model_canonical'] for t in ordered if t is not s)
            sign = 1 if g['direction']=='higher' else -1
            for a,b in combinations(ordered,2):
                y = comparison_target(g,a,b)
                row = (a['model_canonical'],b['model_canonical'],y,
                    pair_weight(weights,g['group_id'],a['model_canonical'],b['model_canonical']))
                contests.append(row)
                per_benchmark[g['paper_id']].append(row)
        connected = components(sources,contests)
        connected.sort(key=lambda ns:(-sum(n in core_names for n in ns),
            -len(set().union(*(set(sources[n]) for n in ns))),-len(ns),tuple(ns)))
        primary = connected[0] if connected else []
        primary_set,pos = set(primary),{name:i for i,name in enumerate(primary)}
        combined = defaultdict(lambda:[0.0,0.0])
        for a,b,y,w in contests:
            if a in primary_set:
                combined[pos[a],pos[b]][0] += w*y
                combined[pos[a],pos[b]][1] += w
        edges = [(a,b,win/weight,weight) for (a,b),(win,weight) in sorted(combined.items())]
        layout=graph(primary,groups,weights,comparison_target,fit_prior,coupling_strength=GLOBAL_COUPLING_STRENGTH,source_factor=task_audit['prior_factor'])
        baseline_theta,baseline_fit=fit_graph(layout)
        baseline_edges=list(layout['edges'])
        baseline_clusters=layout['clusters']
        eligible_names = [n for n in primary if n in core_names]
        if len(eligible_names)<2:
            eligible_names = []
        common_calibration=attach_common_calibration(layout,groups,primary,eligible_names,comparison_target,task_audit['prior_factor'])
        theta,fitted=fit_graph(layout,max_iterations=120)
        center = fmean(theta[pos[n]] for n in eligible_names) if eligible_names else 0
        reference_id = digest([POLICY,setting,eligible_names])[:24]
        clusters = {b:[(pos[a],pos[c],y,w) for a,c,y,w in rows if a in primary_set] for b,rows in per_benchmark.items()}
        clusters = {b:rows for b,rows in clusters.items() if rows}
        # Macro-task normalization applies an arbitrary common loss multiplier.
        # Undo that scalar for Fisher-information units; otherwise adding audited
        # task labels widens intervals purely by changing the loss convention.
        # Cluster sandwich variance is invariant to this common rescaling.
        uncertainty_scale=1/task_audit['prior_factor'] if task_audit['prior_factor'] else 1.
        uncertainty_edges=[(a,b,y,w*uncertainty_scale)for a,b,y,w in layout['edges']]
        uncertainty_clusters={p:[(a,b,y,w*uncertainty_scale)for a,b,y,w in rows]for p,rows in layout['clusters'].items()}
        intervals = uncertainty(theta,uncertainty_edges,uncertainty_clusters,[pos[n] for n in eligible_names],
            [p*uncertainty_scale for p in layout['priors']],
            quadratic_edges=[(a,b,m,w*uncertainty_scale)for a,b,m,w in layout.get('quadratic_edges',[])],
            cluster_gradients=cluster_gradients(common_calibration,pos,theta,uncertainty_scale)) if fitted['converged'] and compute_uncertainty else {}
        # A source-derived penalty must not manufacture precision. Keep at
        # least the uncertainty of the uncalibrated fit on the same evidence.
        from collections import defaultdict as _defaultdict
        family_by_paper={g['paper_id']:g.get('calibration_paper_identity','paper:'+g['paper_id'])for g in groups}
        base_clusters=_defaultdict(list)
        for paper,rows in baseline_clusters.items():
            base_clusters[family_by_paper.get(paper,paper)].extend((a,b,y,w*uncertainty_scale)for a,b,y,w in rows)
        baseline_intervals=uncertainty(baseline_theta,[(a,b,y,w*uncertainty_scale)for a,b,y,w in baseline_edges],
            dict(base_clusters),[pos[n]for n in eligible_names],[p*uncertainty_scale for p in layout['priors']]) if baseline_fit['converged'] and compute_uncertainty else {}
        for i,interval in intervals.items():
            interval['conditional_calibrated_standard_error']=interval['standard_error']
            interval['uncalibrated_standard_error_floor']=baseline_intervals[i]['standard_error']
            interval['standard_error']=max(interval['standard_error'],baseline_intervals[i]['standard_error'])
        calibrated={n:theta[pos[n]] for n in primary}
        consistency=dict(enabled=False,constraints=0,rules=[],changed_models=0,conflicting_cycles=[],
            policy='RETIRED_SCORE_ORDER_PROJECTION',reason='No hard projection. Repeated common-source calibration, including a disclosed finite within-vendor penalty, is part of the fitted objective; no release-order input.')
        conditional={}
        published = []
        membership = {n:digest(c)[:16] for c in connected for n in c}
        for model in index['models']:
            if model['model_setting']!=setting:
                continue
            name = model['model_canonical']
            benchmarks = sources.get(name,{})
            eligible = name in eligible_names and fitted['converged']
            role_issue = general_model_issue(name)
            status = ('ELIGIBLE' if eligible else 'SPECIALIZED_MODEL_OUTSIDE_GENERAL_INDEX' if role_issue
                      else 'BROAD_COVERAGE_REQUIRED' if name not in core_names else 'DISCONNECTED_COMPARISON_GRAPH' if name not in primary_set
                      else 'FIT_NOT_CONVERGED' if not fitted['converged'] else 'INSUFFICIENT_CONNECTED_MODELS'
                      if len(benchmarks)>=minimum and not eligible_names else 'INSUFFICIENT_SCORABLE_BENCHMARKS')
            entries,benchmark_scores = [],[]
            for benchmark in sorted(benchmarks):
                rows = benchmarks[benchmark]
                benchmark_scores.append(dict(benchmark_identity=benchmark,score=fmean(s['pairwise_score'] for _,s in rows),
                    score_meaning='Observed same-source win fraction; diagnostic only, not additive BT contributions.',
                    group_ids=[g['group_id'] for g,_ in rows],source_keys=[list(x) for x in sorted({(g['paper_id'],g['benchmark_id']) for g,_ in rows})]))
                for g,s in rows:
                    ref = g['reference_profile']
                    entries.append({**{k:g[k] for k in ('group_id','benchmark_id','paper_id','table_id','metric','row_key','direction')},
                        'benchmark_identity':benchmark,'raw_value':s['value_numeric'],
                        'normalized_score':s['pairwise_score']/100,'score_unit':'source_pairwise_win_fraction',
                        'comparison_target':fmean(comparison_target(g,s,t) for t in g['scores'] if t is not s),
                        'comparison_scale_sd':ref['standard_deviation'],
                        'comparison_scale':ref['contrast_scale'],'comparison_method':ref['contrast_method'],
                        'information_weight':ref['information_weight'],
                        'task_strata':g['task_balance_strata'],'task_balance_factor':g['task_balance_factor'],
                        'temporal_weight':g['temporal_weight'],'temporal_provenance':g['temporal_provenance'],
                        'weight':sum(pair_weight(weights,g['group_id'],a['model_canonical'],b['model_canonical'])
                            for a,b in combinations(g['scores'],2)),
                        'pair_weight':fmean(pair_weight(weights,g['group_id'],name,t['model_canonical']) for t in g['scores'] if t is not s),
                        'opponent_pair_weights':{t['model_canonical']:pair_weight(weights,g['group_id'],name,t['model_canonical'])
                            for t in g['scores'] if t is not s},
                        'opponents':sorted(t['model_canonical'] for t in g['scores'] if t['model_canonical']!=name),
                        'reference_id':ref['reference_id'],'reference_count':ref['reference_count'],
                        'observation_ids':s.get('observation_ids',[])})
            task_strengths=[]
            for (head_name,task),head_pos in layout['heads'].items():
                if head_name!=name:continue
                task_rows=[(g,s) for rows in benchmarks.values() for g,s in rows if task in g['task_balance_strata']]
                task_strengths.append(dict(task_stratum=task,strength=theta[head_pos],
                    shared_strength=theta[pos[name]],task_deviation=theta[head_pos]-theta[pos[name]],
                    benchmarks=len({_benchmark(g) for g,_ in task_rows}),source_papers=len({g['paper_id'] for g,_ in task_rows})))
            strength = theta[pos[name]]-center if name in primary_set else None
            base_score = display_score(strength) if eligible else None
            calibrated_strength=calibrated[name]-center if name in primary_set else None
            score = round(display_score(calibrated_strength),6) if eligible else None
            interval = intervals.get(pos.get(name)) if eligible else None
            se = interval['standard_error'] if interval else None
            adjusted_interval=conditional.get(pos.get(name),interval)
            score_se=max(se,adjusted_interval['standard_error'])if se is not None else None
            related_rules=[r for r in consistency['rules']if name in (r['winner'],r['loser'])]
            model.update(score=score,publication_score=score,publication_eligible=eligible,publication_status=status,
                comparison_scope='GLOBAL_CONNECTED_PAIRED_COMPARISONS',score_unit='composite_0_100',
                score_panel_id='global:'+version,score_version=version,score_components=entries,
                aggregate_z=None,unshrunk_z=None,evidence_reliability=None,prior_strength=fit_prior,
                bt_strength=theta[pos[name]] if name in primary_set else None,bt_centered_strength=strength,
                bt_reference_id=reference_id,bt_standard_error=se,bt_uncertainty=interval,
                base_publication_score=base_score,
                base_score_interval=[display_score(strength-1.96*se),display_score(strength+1.96*se)] if se is not None else None,
                score_interval=[display_score(calibrated_strength-1.96*score_se),display_score(calibrated_strength+1.96*score_se)] if score_se is not None else None,
                score_uncertainty=dict(adjusted_interval,standard_error=score_se,base_variance_floor=True,
                    conditioning='Conditional soft-calibrated working interval with original-paper-family clusters and uncalibrated variance floor. Rule-selection uncertainty is not fully estimated; not unconditional rank coverage.')if adjusted_interval else None,
                common_source_calibration=dict(policy=common_calibration['policy'],
                    direct_relations=sum(name in (r['a'],r['b'])for r in common_calibration['rules']),
                    within_vendor_relations=sum(r['within_vendor']and name in (r['a'],r['b'])for r in common_calibration['rules']),
                    uncalibrated_strength=baseline_theta[pos[name]] if name in primary_set else None),
                source_consensus=None,temporal_scoring=temporal,
                rank_interval=None,ranking_evidence=None,rank_interval_method='not_estimated',
                rank_population=len(eligible_names),direct_opponents=len(opponents.get(name,set())),
                comparison_component=membership.get(name),ranking_confidence='LIMITED_COVERAGE' if len(benchmarks)<10 else 'REGULARIZED_SHARED_STRENGTH',
                scored_benchmarks=len(benchmarks),scored_groups=len(entries),global_benchmark_scores=benchmark_scores,
                scored_source_papers=len({c['paper_id'] for c in entries}),
                core_benchmarks=len(core_benchmarks.get(name,set())),core_source_papers=len(core_papers.get(name,set())),
                available_benchmarks=len(available_sources.get(name,set())),available_source_papers=len(available_papers.get(name,set())),
                general_model_issue=role_issue,fitted_task_strengths=task_strengths,
                shared_strength_model=True,observed_task_strata=[r['task_stratum'] for r in task_strengths],
                publication_min_source_papers=MIN_SOURCE_PAPERS,
                score_coverage=len(benchmarks)/len(benchmark_counts) if benchmark_counts else 0,
                score_coverage_denominator=len(benchmark_counts),missing_score_groups=[],required_score_groups=0,
                provisional=not eligible,status='COMPLETE' if eligible else 'PARTIAL',
                other_source_conflicts=model.get('other_source_conflicts',model.get('blocked_group_ids',[])),blocked_group_ids=[])
            if eligible:
                published.append(model)
        ordered = sorted(published, key=lambda m: (-m['score'], m['model_canonical']))
        for position, m in enumerate(ordered):
            above = ordered[position-1] if position else None
            proof = comparison_evidence(groups, m['model_canonical'], above['model_canonical']) if above else None
            m['ranking_evidence'] = dict(point_estimate_position=position+1,
                order_status='SOURCE_FITTED_POINT_ESTIMATE',
                above_model=above['model_canonical'] if above else None,
                above_comparison=proof,
                interpretation='Soft-calibrated shared-strength estimate. Repeated consistent common-source directions receive finite regularization, stronger within known vendors. No release-order or hard rank projection. Adjacent evidence remains inspectable.')
        summaries.append(dict(model_setting=setting,reference_groups=len(groups),reference_benchmarks=len(benchmark_counts),
            core_selection=core_audit,source_papers=len({g['paper_id'] for g in groups}),
            published_models=len(published),status='PUBLISHED' if published else 'INSUFFICIENT_EVIDENCE',
            components=len(connected),component_sizes=[len(c) for c in connected],primary_component=primary,
            reference_cohort=eligible_names,reference_id=reference_id,center=center,fit=fitted,
            pair_records=len(contests),unique_pairs=len(edges),prior_strength=fit_prior,task_balance=task_audit,
            source_weighting=weights.audit,temporal_scoring=temporal,
            consensus_projection=consistency,common_source_calibration=common_calibration,
            latent_fit=dict(node_labels=layout['node_labels'],strengths=theta,prior_weights=layout['priors'],
                coupling_strength=GLOBAL_COUPLING_STRENGTH,coupling_weight=layout['coupling_weight'],
                observed_pairs=len(layout['observed_edges']),penalty_terms=len(layout['penalty_edges']))))
    index['score_panels'] = []
    index.pop('score_panel',None)
    index['method'] = dict(name='source_balanced_task_composite',version=16,score_unit='composite_0_100',
        score_version=version,global_composite=True,opponent_adjusted=True,min_benchmarks=minimum,
        minimum_connected_models=2,min_source_papers=MIN_SOURCE_PAPERS,panel_status='CONFIGURED',
        quality_policy=QUALITY_POLICY,
        measurement_policy=MEASUREMENT_POLICY,neutral_prior_calibration=dict(CALIBRATION,applied_strength=prior_strength),
        uncertainty_policy=UNCERTAINTY_POLICY,
        source_budget_calibration=SOURCE_CALIBRATION,source_budget_policy=SOURCE_BUDGET_POLICY,
        source_context_policy=SOURCE_CONTEXT_POLICY,vendor_consistency=dict(enabled=False,kind='NONE',hard_projection=False),
        common_source_calibration=COMMON_CALIBRATION,
        metric_policy='Only final task performance enters capability fits. Source-defined prompt/intervention gains and statistical diagnostics are separate measurement kinds. Bootstrap estimates of final performance remain eligible; a delta glyph alone does not establish an intervention effect. All original measurements remain in raw evidence.',
        group_formula='For >=3 references use sigmoid(direction*(raw_i-raw_j)/source_SD). For two references use verified quarter-range, else same-source peer SD; without an independent scale retain ordinal .75/.25/.5 at half information weight. No fabricated continuous margin.',
        margin_temperature=MARGIN_TEMPERATURE,
        task_balance='Exact source-audited task labels define strata. When taxonomy tasks are absent, independently supported capability evidence can recover visual, audio, document or safety strata with its quotes retained. Generic reasoning and model names never supply task labels. Recovered labels retain their original macro-source budget and only change task-fit heads; metadata recovery cannot multiply evidence. Multi-label sources split budget; missing outcomes are not imputed.',
        aggregation='Unprojected same-task/shared-strength fit with model-incidence source budgets. Each model/source budget is <=1 before task/information factors and common mass rescaling. Target-identity diagnostics, condition gains and explicitly secondary inference modes do not enter default general scores. Original records remain available.',
        reference_policy=f'Publication and reference center require an incidence-selected connected comparison core: iteratively retain contests with >=2 general models and models with >={minimum} distinct benchmark identities in those contests. No extra source-paper count threshold. Auxiliary models preserve observed calibration information. Source task specialization is fitted separately from shared strength. Selection never uses outcomes, age, vendor or UI selection. Evidence quantity is handled by source budgets, neutral regularization and source-paper uncertainty, not an added sparse-model score penalty.',
        prior_strength=prior_strength,prior_mean_strength=0,task_coupling_strength=GLOBAL_COUPLING_STRENGTH,
        strength_model='Regularized shared and observed-task strengths from real source pairs. Repeated consistent source means calibrate shared strengths with the same finite rule for every model pair. No vendor grouping, model-age, expected version order or hard projection.',
        regularization=f'Neutral penalty {prior_strength}, own-task coupling {GLOBAL_COUPLING_STRENGTH}, vendor-blind repeated-source direct calibration 2. No manufacturer, model age or version-order penalty. Historical calibration validation does not establish accuracy of this revised policy.',
        hard_order_projection=False,temporal_scoring=temporal,
        display_formula='round(100 * sigmoid(shared_strength - mean_eligible_shared_strength), 6)',
        score_meaning='Time-weighted shared cross-task relative performance on the declared source/task distribution; not accuracy or universal ability.',
        uncertainty='Conditional soft-calibrated information/paper-family influence interval, floored by the uncalibrated-fit uncertainty on the same data. Repeated calibration terms are assigned to original source families, never counted as extra independent papers. Rule-selection uncertainty remains a limitation; not a bootstrap or joint rank guarantee.',
        missing_data=f'No imputed outcomes. At least {minimum} distinct benchmark identities in the connected comparison core. No additional paper-count gate. Source-poor results retain paper-cluster uncertainty; fewer than {minimum} benchmarks or specialized models retain single-benchmark evidence.',
        ranking_policy='Order by the jointly fitted score with vendor-blind repeated-source direct calibration. No manufacturer or model-age input and no prescribed newest-first order. Conflicting evidence can retain reversals. UI selection changes display only.',
        interpretation='One data-derived connected reference per setting. UI selection never changes scores; heterogeneous coverage remains a limitation.')
    index['relative_reference_audit'] = dict(status='READY',policy=POLICY,counts=counts,settings=summaries,reference_groups=len(references),model_calls=0)
    index['automatic_scoring'] = dict(status='PUBLISHED' if any(s['published_models'] for s in summaries) else 'INSUFFICIENT_EVIDENCE',
        panels=0,global_composite=True,published_models=sum(s['published_models'] for s in summaries),minimum_benchmarks=minimum,
        reason=f'综合榜仅汇总最终任务表现；提示或干预增益、统计诊断量保留原值另列。需在真实比较网络内具有至少 {minimum} 项可比 Benchmark；按模型对分摊来源预算，任务内采用温和时间衰减，联合拟合任务表现与综合强度。')
    index['publication_quality_audit'] = dict(policy=QUALITY_POLICY,
        identity_exclusions=dict(Counter(e['reason'] for e in index.get('exclusions', [])
            if e['reason'] in {'ambiguous_model_name', 'unspecified_model_version', 'non_base_model_source', 'noncomparable_source'})),
        identity_excluded_records=len({oid for e in index.get('exclusions', [])
            if e['reason'] in {'ambiguous_model_name', 'unspecified_model_version', 'non_base_model_source', 'noncomparable_source'}
            for oid in e['observation_ids']}),
        non_capability_groups=sum(g['metric_role']!='PERFORMANCE' for g in index['groups']),
        metric_roles=dict(Counter(g['metric_role'] for g in index['groups'])),
        measurement_kinds=dict(Counter(g['measurement_kind'] for g in index['groups'])),
        source_policy='Original labels, settings, values and coordinates preserved; no unknown name is guessed into a parent model.', model_calls=0)
    return index


def comparison_evidence(groups, name, opponent):
    """Exact same-condition outcomes, equal-weighted within each benchmark.

    This is a descriptive diagnostic, not a significance test or a new score.
    In particular, zero common groups is not a tie.
    """
    benchmarks = defaultdict(list)
    for g in groups:
        values = {s['model_canonical']:s['value_numeric'] for s in g['scores']}
        if name not in values or opponent not in values:
            continue
        delta = (values[name]-values[opponent])*(1 if g['direction']=='higher' else -1)
        benchmarks[_benchmark(g)].append(dict(group_id=g['group_id'], outcome=.5 if delta==0 else float(delta>0)))
    rows = [dict(benchmark_identity=b, win_fraction=fmean(x['outcome'] for x in entries),
                 group_ids=[x['group_id'] for x in entries]) for b,entries in sorted(benchmarks.items())]
    return dict(opponent=opponent, shared_benchmarks=len(rows), shared_groups=sum(len(r['group_ids']) for r in rows),
        benchmark_wins=sum(r['win_fraction']>.5 for r in rows), benchmark_ties=sum(r['win_fraction']==.5 for r in rows),
        benchmark_losses=sum(r['win_fraction']<.5 for r in rows),
        mean_win_fraction=fmean(r['win_fraction'] for r in rows) if rows else None,
        basis='same-condition groups; metrics equally weighted within each benchmark; no missing outcome imputation', benchmarks=rows)
