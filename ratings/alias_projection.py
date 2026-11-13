"""Apply source-reviewed aliases before comparison construction, never after fitting."""
from collections import defaultdict
from copy import deepcopy
from itertools import combinations
import re
from math import isclose

POLICY='reviewed-source-alias-projection-v1'

def normalize_configuration(value):
    if value is None:return None
    value=value.strip().casefold()
    if value in {'adaptive-max','adaptive/max','adaptive max'}:return 'adaptive/max'
    if value in {'max','high','xhigh','medium','low'}:return value
    raise ValueError('Unreviewed configuration spelling: '+value)

def validate_alias(old,new):
    old_match=re.fullmatch(r'(?i)Fable\s*(5(?:\.1)?)',old)
    new_match=re.fullmatch(r'Claude Fable (5(?:\.1)?)',new)
    if not old_match or not new_match or old_match[1]!=new_match[1]:
        raise ValueError('Alias must preserve the reviewed model family and exact version')

def mapped_name(pid,name,setting,registry):
    entry=registry.get((pid,name,setting))
    if entry:
        validate_alias(name,entry['canonical_name'])
        config=normalize_configuration(entry.get('configuration'))
        return entry['canonical_name']+(' ('+config+')' if config else '')
    # This exact explicit spelling is already present in the frozen data.
    # It is formatting-equivalent to the independently source-verified API form.
    match=re.fullmatch(r'(?i)(Claude Fable 5(?:\.1)?) adaptive/Max',name)
    if match:return match[1]+' (adaptive/max)'
    return name

def project_records(data,raw,registry):
    bygroup=defaultdict(list)
    for record in raw:bygroup[record['group_id']].append(record)
    groups={g['group_id']:g for g in data['index']['groups']}
    output=[];changes=[];conflicts=[];merged=[];audit=[]
    for gid,records in bygroup.items():
        group=groups[gid];pid=group['paper_id'];setting=group.get('model_setting','')
        original_nodes={tuple(record[k])for record in records for k in ('a','b')}
        replacement={node:(mapped_name(pid,node[0],setting,registry),node[1])for node in original_nodes}
        if all(a==b for a,b in replacement.items()):
            output.extend(deepcopy(records));continue
        buckets=defaultdict(list)
        for score in group['scores']:
            old=(score['model_canonical'],score.get('dedup_condition',setting or group.get('source_condition_key','')))
            if old not in original_nodes:continue
            target=replacement[old]
            buckets[target].append(score)
            if old!=target:
                changes.append({'paper_id':pid,'table_id':group['table_id'],'group_id':gid,
                    'old_node':old,'new_node':target,'value_numeric':score['value_numeric'],
                    'observation_ids':score.get('observation_ids',[]),'source_records':score.get('task_source_records',[])})
        accepted={}
        for node,scores in buckets.items():
            values={s['value_numeric']for s in scores}
            if len(values)!=1:
                conflicts.append({'paper_id':pid,'group_id':gid,'table_id':group['table_id'],
                    'node':node,'values':sorted(values),'reason':'MODEL_ALIAS_SAME_CONDITION_VALUE_CONFLICT',
                    'observation_ids':sorted({oid for s in scores for oid in s.get('observation_ids',[])})})
                continue
            accepted[node]=next(iter(values))
            if len(scores)>1:
                merged.append({'group_id':gid,'node':node,'value_numeric':accepted[node],
                    'source_labels':[s['model_canonical']for s in scores],
                    'observation_ids':sorted({oid for s in scores for oid in s.get('observation_ids',[])})})
        m=len(accepted)
        if m>=2:
            remapped={}
            for record in records:
                a,b=(replacement[tuple(record[k])] for k in ('a','b'))
                if a==b or a not in accepted or b not in accepted:continue
                y=record['y']
                if a>b:a,b,y=b,a,1-y
                if (a,b) in remapped:
                    if not isclose(remapped[a,b]['y'],y,abs_tol=1e-12):
                        raise ValueError('Conflicting outcomes for merged alias pair')
                    continue
                remapped[a,b]={**record,'a':list(a),'b':list(b),'y':y,'m':m,'w':record['q']/(m-1)}
            # Identity projection must not recreate hard wins or copy the first
            # pair's observation metadata to every pair in the source table.
            output.extend(remapped[k] for k in sorted(remapped))
        audit.append({'group_id':gid,'paper_id':pid,'comparisons_before':len(records),
            'comparisons_after':m*(m-1)//2,'nodes_before':len(original_nodes),'nodes_after':m})
    return output,{'policy':POLICY,'snapshot_id':data['snapshot_id'],'changes':changes,
        'merged_same_value_source_rows':merged,'quarantined_same_source_conflicts':conflicts,
        'changed_groups':audit,'comparisons_before':len(raw),'comparisons_after':len(output),
        'original_source_values_changed':False,'fit_outcomes_used_to_choose_aliases':False}
