"""Source-bound task outcomes, subsets and comparison facets.

Rules describe measurements, never preferred model identities or version order.
Raw source records are retained; only the scoring projection is filtered.
"""
import re
from collections import defaultdict

POLICY='source-scoped-task-measurements-v5'
FACETS={
 'software_delivery':'软件工作交付','web_functionality':'网页功能实现',
 'code_implementation':'规格实现与验收','code_repair':'已有代码修复',
 'rtl_generation':'RTL 硬件代码生成','verifier_generation':'验证器生成',
 'medical_knowledge_qa':'医学知识问答','life_science_qa':'生命科学知识问答',
 'medical_guideline_application':'医学指南应用','clinical_delivery':'临床工作交付',
 'clinical_answer_quality':'临床回答质量','clinical_guideline_grading':'临床指南分级',
 'clinical_guideline_grading_ood':'临床指南分级 · 分布外样本',
 'clinical_guideline_grading_hard':'临床指南分级 · 困难样本',
 'biology_knowledge_qa':'生物知识问答','chemistry_knowledge_qa':'化学知识问答',
 'therapy_fidelity_classification':'治疗记录分类','audio_attribute_extraction':'语音属性抽取',
 'entity_linking':'实体链接','document_extraction':'文档信息抽取',
 'mathematical_problem_solving':'数学问题求解','logical_problem_solving':'逻辑问题求解',
 'visual_question_answering':'视觉问答','document_question_answering':'文档问答',
 'finance_delivery':'金融工作交付','legal_delivery':'法律工作交付',
 'industrial_delivery':'工业工作交付','scientific_problem_solving':'科学问题求解',
 'language_generation':'文本生成','source_grounding':'来源一致性',
}
FACET_TASKS={
 'software_delivery':['code_development','tool_workflow','interactive_execution'],
 'web_functionality':['code_development'],'code_implementation':['code_development'],
 'code_repair':['code_development'],'rtl_generation':['code_development'],'verifier_generation':['code_development'],
 'medical_knowledge_qa':['knowledge_qa'],'life_science_qa':['knowledge_qa'],'biology_knowledge_qa':['knowledge_qa'],
 'chemistry_knowledge_qa':['knowledge_qa'],'medical_guideline_application':['knowledge_qa','document_qa'],
 'clinical_delivery':['tool_workflow','interactive_execution'],'clinical_answer_quality':['knowledge_qa','document_qa'],
 'clinical_guideline_grading':['knowledge_qa'],'clinical_guideline_grading_ood':['knowledge_qa'],'clinical_guideline_grading_hard':['knowledge_qa'],
 'therapy_fidelity_classification':['reading_comprehension'],
 'audio_attribute_extraction':['structured_extraction'],'document_extraction':['structured_extraction'],'entity_linking':['structured_extraction'],
 'mathematical_problem_solving':['mathematical_problem_solving'],'logical_problem_solving':['mathematical_problem_solving','data_analysis'],
 'scientific_problem_solving':['knowledge_qa'],'document_question_answering':['document_qa','reading_comprehension'],
 'visual_question_answering':['visual_document_understanding'],'finance_delivery':['tool_workflow','data_analysis'],
 'legal_delivery':['tool_workflow','document_qa'],'industrial_delivery':['tool_workflow','data_analysis'],
 'source_grounding':['document_qa','summarization','literature_review'],'language_generation':['writing','dialogue'],
}

def source_metadata(groups, observations):
    """Join exact observation IDs and source keys, without fuzzy source matching."""
    if observations is None:return
    by_id={o['observation_id']:o for o in observations if o.get('observation_id')}
    table_contexts=defaultdict(set)
    for o in observations:
        context=o.get('scope_evidence')
        if isinstance(context,str) and len(context.strip())>=80:
            table_contexts[o.get('paper_id'),o.get('table_id')].add(context.strip())
    full=defaultdict(set)
    norm=lambda s:re.sub(r'[^a-z0-9]+','',str(s).casefold())
    for o in observations:
        raw=o.get('model_raw')or'';name=o.get('model_canonical')or''
        if norm(raw)==norm(name) and not re.fullmatch(r'(?i)captioner|omni flash',name):full[o.get('paper_id')].add(name)
    for g in groups:
        contexts=table_contexts.get((g['paper_id'],g['table_id']),set())
        if contexts:g['metric_role_context']='\n'.join(sorted(contexts|{g.get('metric_role_context')or''}))
        subsets=set()
        for s in g['scores']:
            records=[by_id[o]for o in s.get('observation_ids',[])if o in by_id
                     and (by_id[o].get('paper_id'),by_id[o].get('table_id'))==(g['paper_id'],g['table_id'])]
            s['task_source_records']=[{k:r.get(k)for k in ('observation_id','model_raw','benchmark','source_row','source_column')}for r in records]
            if re.fullmatch(r'(?i)captioner|omni flash',s['model_canonical']):
                candidates={n for n in full[g['paper_id']]if norm(n).endswith(norm(s['model_canonical']))}
                if len(candidates)==1:
                    s['task_source_model_label']=s['model_canonical'];s['model_canonical']=next(iter(candidates))
                    s['task_identity_basis']='UNIQUE_FULL_SOURCE_LABEL_IN_SAME_PAPER'
            subsets.update(str(r.get('benchmark')or'').strip()for r in records)
        g['task_source_subsets']=sorted(subsets-{''})
        g['task_source_context_verified']=True

def metric_key(metric):return re.sub(r'[↑↓%()\s.]+','',str(metric)).casefold()

def inspect(group,benchmark,profile):
    requested=set(benchmark['matched_capabilities'])
    metric=metric_key(group['metric']);text=' '.join(str(group.get('metric_role_context')or'').split()).casefold()
    quotes='\n'.join(str(e.get('quote')or'')for e in benchmark.get('label_evidence',[])).casefold()
    evidence=text+'\n'+quotes;domains=set(profile.get('domains',[]));tasks=set(profile.get('tasks',[]))
    subsets={s.casefold()for s in group.get('task_source_subsets',[])}
    def reject(reason):return dict(capabilities=[],facet=None,basis='AUXILIARY',reason=reason)
    def related():
        # An audited catalogue binding establishes relevance, not that every
        # table column measures the user's exact task. Keep this source in a
        # separate reference panel instead of either discarding it or mixing
        # its outcomes into an unrelated task score.
        from .publication_quality import metric_role
        if metric_role(group['metric'],group.get('metric_role_context',''))!='PERFORMANCE':
            return reject('auxiliary_or_diagnostic_measurement')
        identity=benchmark.get('benchmark_identity')or benchmark['benchmark_id']
        return dict(capabilities=sorted(requested),facet='related_reference:'+str(benchmark.get('benchmark_name')or identity)+':'+identity,
                    tasks=[],basis='CATALOG_RELATED_REFERENCE',reason=None)
    def result(caps,facet,**extra):
        chosen=sorted(set(caps)&requested)
        if ((facet=='code_implementation'and 'two workflows'in text)
            or(facet=='web_functionality'and 'results by task starting point'in text)
            or facet=='therapy_fidelity_classification'):
            # Source captions establish different conditions, but this legacy
            # extraction did not retain their labels as model settings. Keep
            # each exact source group separate instead of averaging methods.
            facet+=':condition:'+group['group_id']
        return dict(capabilities=chosen,facet=facet,tasks=extra.pop('tasks',FACET_TASKS.get(facet.split(':condition:')[0],[])),basis='SOURCE_SCOPED_TASK_OUTCOME',
                    reason=None if chosen else 'no_metric_level_task_binding',**extra)
    if re.search(r'pairwise inter.annotator agreement|inter.rater agreement|annotator agreement',text):
        return reject('source_caption_reports_annotation_agreement')
    from .task_measurement_policy import task_metric_role
    role=task_metric_role(group)
    if role!='PERFORMANCE':
        return reject('task_measurement_role:'+role)
    if re.search(r'summarizer backbone|continuation agent|recurring.detail retention|task preservation damage',text):
        return reject('summarizer_or_compaction_not_coding_agent')
    if metric=='ldpr':return reject('metric_meaning_not_established_by_source_caption')
    if re.search(r'^(?:gap|kbs|gcs|hallucination|wrongspan|termmismatch|partial|noise|known.case|null.as.zero)',metric):
        return reject('auxiliary_or_diagnostic_measurement')
    if 'domain abbreviations denote'in text and 'software work'in text:
        bindings={'soft':('software','software_delivery',['code_correctness']),
                  'clin':('medicine','clinical_delivery',['domain_knowledge']),
                  'fin':('finance','finance_delivery',['domain_knowledge']),
                  'legal':('law','legal_delivery',['domain_knowledge']),
                  'ind':('science','industrial_delivery',['domain_knowledge'])}
        if metric not in bindings:return reject('other_domain_or_mixed_domain_result')
        domain,facet,caps=bindings[metric]
        if domains and domain not in domains:return reject('other_domain_or_mixed_domain_result')
        return result(caps,facet,percentage=True)
    if 'code_development'in tasks or requested&{'code_correctness','code_debugging'}:
        if 'implementation score'in str(group['metric']).casefold() and re.search(r'acceptance testing|code acceptance',quotes):
            return result(['code_correctness'],'code_implementation',percentage=True)
        if metric=='fs'and ('functional'in text or 'functional score'in quotes):return result(['code_correctness'],'web_functionality')
        if metric=='rs'and 'requirement satisfaction'in evidence:return result(['instruction_following'],'web_functionality')
        if metric=='residual'and 'residual reports success'in text:return result(['code_correctness','code_debugging'],'code_repair',percentage=True)
        if metric.startswith('scalebench')and 'pass@1'in quotes and 'rtl'in quotes:return result(['code_correctness'],'rtl_generation',percentage=True)
        if metric.startswith('banorm')and 'verifier generation'in quotes:return result(['code_correctness'],'verifier_generation')
        if metric in {'accuracy','successrate'}and 'code acceptance'in text:return result(['code_correctness'],'code_implementation')
        if metric in {'tpr','tnr','fprh'}:return reject('verifier_component_not_overall_coding_outcome')
    if 'recognition'in text and 'incorporation'in text:
        if metric=='clinical':return result(['domain_knowledge','factual_accuracy'],'medical_guideline_application',percentage=True)
        if metric=='fullincorporation':return result(['grounded_faithfulness'],'medical_guideline_application',percentage=True)
        return reject('recognition_or_gap_not_final_guideline_application')
    if 'lg-bench'in evidence and metric=='acc':
        if 'medicine'in domains or subsets=={'medicine'}:
            if subsets and subsets!={'medicine'}:return reject('other_domain_or_mixed_domain_result')
            if not subsets:return reject('source_subset_not_established')
            if domains and 'medicine'not in domains:return reject('other_domain_or_mixed_domain_result')
            return result(['domain_knowledge','factual_accuracy'],'medical_knowledge_qa',percentage=True)
        if 'science'in domains and subsets&{'medicine','overall'}:return reject('other_domain_or_mixed_domain_result')
        facet={'biology':'biology_knowledge_qa','chemistry':'chemistry_knowledge_qa'}.get(next(iter(subsets))if len(subsets)==1 else '', 'life_science_qa')
        return result(['domain_knowledge','factual_accuracy'],facet,percentage=True)
    if 'accuracy on retijev-bench'in text:
        if metric in {'ood','hard','unseen','seen'}:return result(['domain_knowledge','factual_accuracy'],'clinical_guideline_grading_'+metric if metric in {'ood','hard'}else 'clinical_guideline_grading',percentage=True)
    if 'error taxonomy'in text:
        if metric=='correct'and 'clinical'in quotes:return result(['domain_knowledge','factual_accuracy'],'clinical_answer_quality',percentage=True)
        return reject('auxiliary_or_diagnostic_measurement')
    if 'fidelity estimation'in text and metric=='ba':return result(['domain_knowledge'],'therapy_fidelity_classification')
    if 'tag-bench'in evidence and ('structured19'in metric or ('structured'in metric and 'known'not in metric)):
        return result(['information_extraction','audio_understanding'],'audio_attribute_extraction')
    if 'tag-bench'in evidence:return reject('mixed_descriptive_or_missingness_diagnostic')
    # Generic bindings need an outcome metric AND a source definition of the task.
    outcome=bool(re.fullmatch(r'(?:accuracy|acc|correct|f1|microf1|macrof1|em|exactmatch|successrate|pass@?\d+|score|overall)',metric))
    if not outcome:return related()
    if re.search(r'entity linking',evidence):return result(['information_extraction'],'entity_linking')
    if re.search(r'information extraction|field extraction|structured extraction|extract.{0,35}(?:entit|relation|field)',evidence):
        return result(['information_extraction'],'document_extraction')
    scope=text+' '+' '.join(subsets)
    catalogue=benchmark.get('catalog_labels',{})
    task_evidence=scope if (len(catalogue.get('tasks',[]))>1 or len(catalogue.get('domains',[]))>1) else evidence
    if re.search(r'mathematical|math problem|mathematics|theorem|proof',task_evidence):
        return result(['reasoning','mathematical_reasoning'],'mathematical_problem_solving')
    if re.search(r'logical reasoning|reasoning tasks|constraint satisfaction',task_evidence):return result(['reasoning','logical_reasoning'],'logical_problem_solving')
    if re.search(r'visual question.answer|image question.answer',task_evidence):return result(['visual_perception','multimodal_understanding'],'visual_question_answering')
    if re.search(r'document question.answer|reading comprehension',task_evidence):return result(['reading_comprehension'],'document_question_answering')
    if re.search(r'(?:clinical|medical|medicine).{0,70}(?:question|knowledge|accuracy)|(?:question|knowledge).{0,70}(?:clinical|medical)',task_evidence):
        return result(['domain_knowledge','factual_accuracy'],'medical_knowledge_qa')
    if re.search(r'scientific question|science question|scientific reasoning',task_evidence):return result(['domain_knowledge','reasoning'],'scientific_problem_solving')
    if re.search(r'instruction.following|format compliance',evidence):return result(['instruction_following'],'language_generation')
    if re.search(r'faithfulness|source.grounded|citation correctness',evidence):
        measured_tasks=[]
        for task,pattern in [('document_qa',r'document question.answer'),('summarization',r'summarization|summary generation'),('literature_review',r'literature review|literature synthesis')]:
            if re.search(pattern,task_evidence):measured_tasks.append(task)
        return result(['grounded_faithfulness','citation_reliability'],'source_grounding',tasks=measured_tasks)
    return related()

def safe_scores(group,measurement):
    kept=[];excluded=[]
    for s in group['scores']:
        reason=None
        value=s['value_numeric']
        if measurement.get('percentage')and not 0<=value<=100:reason='source_value_outside_declared_percentage'
        raw=[r.get('model_raw')or''for r in s.get('task_source_records',[])]
        # A size may not be silently added to a family-only source label.
        sizes=re.findall(r'(?i)\b\d+(?:\.\d+)?\s*[bt]\b',s['model_canonical'])
        if raw and sizes and not any(all(re.sub(r'\s+','',v).casefold()in re.sub(r'\s+','',r).casefold()for v in sizes)for r in raw):
            reason='model_size_not_established_by_source_label'
        if re.fullmatch(r'(?i)(?:captioner|omni flash|single|ensemble|ours|baseline)',s['model_canonical']):reason='ambiguous_source_model_identity'
        if reason:excluded.append({'model_canonical':s['model_canonical'],'reason':reason,'observation_ids':s.get('observation_ids',[])})
        else:kept.append(s)
    return kept,excluded

def facet_labels(facets):
    facets=set(facets);labels=dict(FACETS);conditions=defaultdict(list)
    for f in facets:
        if f.startswith('related_reference:'):labels[f]='相关能力参考 · '+f.split(':')[1]
        if ':condition:'in f:conditions[f.split(':condition:')[0]].append(f)
    for base,keys in conditions.items():
        for i,f in enumerate(sorted(keys),1):labels[f]=FACETS.get(base,base)+' · 来源条件 '+str(i)
    names={'non-thinking':'非思考模式','zs':'零样本','cot':'思维链','zs+d':'零样本＋描述','tree':'树搜索','tree+d':'树搜索＋描述'}
    for f in facets:
        if ':protocol:' in f:
            base,protocol=f.rsplit(':protocol:',1)
            base_label=labels.get(base,FACETS.get(base,base))
            if base.startswith('related_reference:'):base_label='相关能力参考 · '+base.split(':')[1]
            labels[f]=base_label+' · '+names.get(protocol,protocol)
    return labels


def condition_measurement(measurement,group):
    if measurement.get('facet') and group.get('source_condition_key'):
        return {**measurement,'facet':measurement['facet']+':protocol:'+group['source_condition_key'].removeprefix('source:')}
    return measurement


def projection(index,catalog,snapshot_id):
    """Compact authoritative preview; same rules and source guards as scoring."""
    sources={(b['paper_id'],b['benchmark_id']):b for b in catalog};items={}
    domains={'clinical_delivery':['medicine'],'medical_knowledge_qa':['medicine'],
             'life_science_qa':['science'],'biology_knowledge_qa':['science'],'chemistry_knowledge_qa':['science'],'finance_delivery':['finance'],'legal_delivery':['law'],
             'industrial_delivery':['science'],'software_delivery':['software']}
    for g in index['groups']:
        b=sources.get((g['paper_id'],g['benchmark_id']))
        if not b:continue
        profile={'domains':[],'tasks':[]}
        bound={**b,'matched_capabilities':b['catalog_labels']['capabilities']}
        measurement=condition_measurement(inspect(g,bound,profile),g)
        from .task_measurement_policy import task_metric_role
        if task_metric_role(g)!='PERFORMANCE':
            measurement=dict(capabilities=[],facet=None,tasks=[],reason='task_measurement_role:'+task_metric_role(g))
        scores,bad=safe_scores(g,measurement)
        items[g['group_id']]={'capabilities':measurement['capabilities'],'facet':measurement['facet'],
                             'tasks':measurement.get('tasks',[]),
                             'domains':domains.get((measurement['facet']or'').split(':protocol:')[0],[]),'models':[s['model_canonical']for s in scores],
                             'aliases':{s['task_source_model_label']:s['model_canonical']for s in scores if s.get('task_source_model_label')},
                             'reason':measurement['reason'],'excluded':bad}
    return {'schema_version':POLICY,'snapshot_id':snapshot_id,'groups':items,'facets':facet_labels(x['facet']for x in items.values()if x['facet'])}
