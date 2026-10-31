"""Separate task facets; direct references for single-benchmark components.

Multiple-source networks use the existing explicit regularized comparison fit.
A one-benchmark source uses its fixed empirical peers directly, with no fitted
neutral parameter or invented bridge to other kinds of task.
"""
from collections import defaultdict
from itertools import combinations
from statistics import fmean
from .global_scoring import prepare_contests,comparison_target
from .balanced_scoring import source_weights,comparison_core
from .source_balanced_scoring import incident_source_weights
from .source_consensus import pair_weight
from .shared_task_scoring import fit_graph
from .paired_scoring import components,sigmoid
from .publication_quality import general_model_issue
from .scoring_preparation import digest
from .relative_scoring import _benchmark
from .temporal_scoring import attach_recency
from .common_source_calibration import attach as calibrate, CALIBRATION

def fit_references(work,matched,*,as_of=None):
    temporal=attach_recency(work,list(matched.values()),as_of=as_of)
    settings,counts=prepare_contests(work,scope='task');result={};audits=[]
    for setting,available in sorted(settings.items()):
        groups=[{**g,'scores':[s for s in g['scores']if not general_model_issue(s['model_canonical'])]}for g in available]
        estimates=defaultdict(lambda:defaultdict(list));keys=defaultdict(list);facets=defaultdict(set)
        refs=defaultdict(set);methods=defaultdict(set)
        for cap,facet in sorted({(c,g['measurement_facet'])for g in groups for c in g['metric_capabilities']}):
            gs=[{**g,'task_balance_factor':g['temporal_weight']}for g in groups if g['measurement_facet']==facet and cap in g['metric_capabilities']]
            names=sorted({s['model_canonical']for g in gs for s in g['scores']});pos={n:i for i,n in enumerate(names)}
            base=source_weights(gs)
            weights=incident_source_weights(gs,{g['group_id']:base[g['group_id']]*g['task_balance_factor']*g['reference_profile'].get('information_weight',1.)for g in gs})
            prior_factor=sum(base[g['group_id']]*g['task_balance_factor']for g in gs)/sum(base.values())
            edges=[(pos[a['model_canonical']],pos[b['model_canonical']],comparison_target(g,a,b),pair_weight(weights,g['group_id'],a['model_canonical'],b['model_canonical']))
                   for g in gs for a,b in combinations(sorted(g['scores'],key=lambda s:s['model_canonical']),2)]
            partitions=components(names,[(names[a],names[b],y,w)for a,b,y,w in edges])
            for partition in partitions:
                pset=set(partition);pg=[g for g in gs if any(s['model_canonical']in pset for s in g['scores'])]
                benches={_benchmark(g)for g in pg};identity=digest([setting,cap,facet,partition,sorted(benches)])[:16]
                if len(benches)==1:
                    # Equal source-paper/group budgets. Scores are fixed relative
                    # to all admissible same-condition peers, never UI selection.
                    by_name=defaultdict(lambda:[0.,0.])
                    for g in pg:
                        for a in g['scores']:
                            opponents=[b for b in g['scores']if b['model_canonical']!=a['model_canonical']]
                            for b in opponents:
                                w=pair_weight(weights,g['group_id'],a['model_canonical'],b['model_canonical'])
                                by_name[a['model_canonical']][0]+=w*comparison_target(g,a,b)
                                by_name[a['model_canonical']][1]+=w
                    values={n:100*by_name[n][0]/by_name[n][1]for n in partition}
                    method='FIXED_SOURCE_PEER_REFERENCE';info={'converged':True,'neutral_prior':None}
                else:
                    local={n:i for i,n in enumerate(partition)}
                    edges_here=[(local[names[a]],local[names[b]],y,w)for a,b,y,w in edges if names[a]in pset and names[b]in pset]
                    clusters=defaultdict(list)
                    for g in pg:
                        for a,b in combinations(g['scores'],2):
                            clusters[g['paper_id']].append((local[a['model_canonical']],local[b['model_canonical']],comparison_target(g,a,b),pair_weight(weights,g['group_id'],a['model_canonical'],b['model_canonical'])))
                    layout={'edges':edges_here,'priors':[.3*prior_factor]*len(partition),'clusters':dict(clusters)}
                    calibration=calibrate(layout,pg,partition,partition,comparison_target,prior_factor)
                    theta,info=fit_graph(layout)
                    info['common_calibration_terms']=calibration['direct_terms']
                    if not info['converged']:raise ArithmeticError('Task facet fit did not converge')
                    _,core=comparison_core(pg);anchors=[n for n in partition if n in core['models']]or partition
                    center=fmean(theta[local[n]]for n in anchors)
                    values={n:100*sigmoid(theta[local[n]]-center)for n in partition};method='MULTI_SOURCE_COMPARISON_NETWORK'
                for n,value in values.items():
                    key=(n,facet)
                    conditions=sorted(g['group_id']for g in pg if any(s['model_canonical']==n for s in g['scores'])) if len(benches)==1 else []
                    estimates[key][cap].append(value);keys[key].append((cap,facet,identity,conditions));facets[key].add(facet);refs[key].update(partition);methods[key].add(method)
                audits.append({'model_setting':setting,'capability_id':cap,'facet':facet,'models':len(partition),'benchmarks':len(benches),
                               'papers':len({g['paper_id']for g in pg}),'method':method,'fit':info,'source_weighting':weights.audit})
        for key,caps in estimates.items():
            name,facet=key
            result[name,setting,facet]={'capabilities':{c:fmean(v)for c,v in caps.items()},'component':digest([setting,sorted(keys[key])])[:16],
                'reference_models':sorted(refs[key]),'shared_strength':None,'measurement_facets':sorted(facets[key]),'reference_methods':sorted(methods[key]),'fit':{'converged':True}}
        for g in available:g['global_status']='CORE_READY'
    return result,{'policy':'shared-source-policy-task-reference-v2','neutral_prior_strength':.3,'task_coupling_strength':0.,'capability_residual_mix':1.,
        'temporal_scoring':temporal,'common_source_calibration':CALIBRATION,'contrast_policy':'Same prepare_contests and comparison_target as global composite.',
        'settings':audits,'counts':counts,'weight_policy':'Independent capability/facet references; same measured facets and source networks define cohorts.',
        'single_source_policy':'Fixed source peer contrast, without fitted neutral shrinkage.','missing_data':'No imputation.','model_calls':0}
