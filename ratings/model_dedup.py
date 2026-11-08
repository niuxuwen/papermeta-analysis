"""Auditable identity projection; no fuzzy matching and no score-based ranking prior."""
import hashlib,json,re,unicodedata
from collections import defaultdict,Counter
from copy import deepcopy
POLICY='source-model-identity-dedup-v1'
FAMILY=re.compile(r'(?i)^(gpt|o[134]|gemini|claude|qwen|deepseek|gemma|llama|llava|glm|kimi|grok|mistral|minimax|internvl|phi|mimo|olmo|molmo|smollm|granite)(?=$|[\s._/\-]|\d)')
EFFORT=r'none|minimal|low|medium|high|xhigh|max|thinking|non-thinking|nothink|think'
SCALE=re.compile(r'(?i)(?<![a-z0-9])(?:\d+(?:\.\d+)?x\d+(?:\.\d+)?[bt]|a?\d+(?:\.\d+)?[bt])(?![a-z0-9])')
def text(s):return ' '.join(unicodedata.normalize('NFKC',s or '').translate(str.maketrans({'–':'-','—':'-','‑':'-','−':'-'})).split())
def tokens(s):return tuple(re.findall(r'[a-z]+|\d+(?:\.\d+)*',s.casefold()))
def norm_effort(s):return {'think':'thinking','nothink':'non-thinking'}.get(s.casefold(),s.casefold())
def identify(name,setting='',records=()):
 original=text(name);n=original;setting=text(setting);proof=[];warnings=[]
 prefixes=[(r'OpenAI[ /]+',r'(?:GPT[ -]?\d|o[134](?:[ -]|$))'),(r'Anthropic[ /]+',r'Claude[ -]+\d'),(r'Google[ /]+',r'(?:Gemini|Gemma)[ -]+\d'),(r'(?:meta-llama|Meta)/',r'Llama[ -]+\d'),(r'Qwen/',r'Qwen[ -]?\d'),(r'deepseek-ai/',r'DeepSeek[ -]?[VR]\d')]
 for prefix,family in prefixes:
  m=re.match('(?i)^'+prefix+'(?='+family+')',n)
  if m:n=n[m.end():];proof.append({'rule':'EXPLICIT_FIRST_PARTY_PREFIX','source_prefix':m[0]});break
 if not FAMILY.match(n):return {'key':('opaque',original,setting),'name':original,'setting':setting,'proof':[],'warnings':['unrecognized_family_identity_not_inferred']}
 for family,producer in [(r'(?:Gemini|Gemma)','Google DeepMind'),(r'GPT','OpenAI'),(r'Claude','Anthropic')]:
  m=re.search(r'\s*\['+re.escape(producer)+r',?\s*20\d\d\]\s*$',n,re.I)
  if m and re.match('(?i)^'+family+r'\b',n):
   proof.append({'rule':'EXPLICIT_BIBLIOGRAPHIC_PRODUCER_YEAR','source_citation':m[0]});n=n[:m.start()]
 # Bibliographic attribution is stripped only for these exact reviewed labels
 # and only when an exact source record confirms the producer/year suffix.
 if re.fullmatch(r'(?i)Gemini 3\.7 Flash Google DeepMind',n):
  evidence=[r for r in records if re.fullmatch(r'(?i)Gemini[ -]+3\.7[ -]+Flash\s+Google DeepMind\s*\(2026\)',text(r.get('model_raw')))]
  if evidence:n='Gemini 3.7 Flash';proof.append({'rule':'REVIEWED_SOURCE_BIBLIOGRAPHIC_ATTRIBUTION','raw_records':evidence})
  else:warnings.append('producer_suffix_without_exact_source_proof')
 # Token order repair is limited to the explicit version/variant grammar.
 n=re.sub(r'(?i)^Claude[ -]+(Opus|Sonnet|Haiku)[ -]+(\d+(?:\.\d+)*)\b',r'Claude \2 \1',n)
 effort=[]
 if re.match(r'(?i)^(?:GPT|o[134]|Claude|Gemini|DeepSeek|Grok|Kimi)\b',n):
  m=re.search(r'(?i)(?:\s*\((?:reasoning(?: effort)?\s*[:=]?\s*)?('+EFFORT+r')\)|[ -]+('+EFFORT+r'))$',n)
  if m:effort.append(norm_effort(m[1]or m[2]));n=n[:m.start()];proof.append({'rule':'EXPLICIT_NAME_EFFORT','effort':effort[-1]})
 conditions=[];setting_scales=[];setting_modes=[]
 for p in re.split(r'[|;]',setting):
  p=p.strip()
  if not p:continue
  m=re.fullmatch(r'(?i)(?:reasoning(?: effort)?\s*[:=]?\s*)?('+EFFORT+r')',p)
  if m:effort.append(norm_effort(m[1]));continue
  if SCALE.fullmatch(p):setting_scales.append(p.upper());continue
  if p.casefold()in {'base','instruct','chat','it','ft'}:setting_modes.append('instruct'if p.casefold()=='it'else p.casefold());continue
  # Case/punctuation are formatting; all unknown protocol words/numbers stay.
  conditions.append(' '.join(p.casefold().split()))
 effort=sorted(set(effort))
 if len(effort)>1:warnings.append('conflicting_effort_fields')
 # Parentheses around a variant are formatting. Their contents are never lost.
 clean=n.replace('(',' ').replace(')',' ').replace('_',' ')
 scales=[m[0].upper()for m in SCALE.finditer(clean)];clean=SCALE.sub(' ',clean)
 modes=[]
 def mode(m):modes.append('instruct'if m[0].casefold()=='it'else m[0].casefold());return ' '
 clean=re.sub(r'(?i)\b(?:instruct|base|chat|it|ft)\b',mode,clean)
 if setting_scales and scales and set(setting_scales)!=set(scales):warnings.append('conflicting_scale_fields')
 if setting_modes and modes and set(setting_modes)!=set(modes):warnings.append('conflicting_training_mode_fields')
 key=('known',tokens(clean),tuple(sorted(set(scales+setting_scales))),tuple(sorted(set(modes+setting_modes))),tuple(effort),tuple(dict.fromkeys(conditions)))
 if not any(re.search(r'\d',x)for x in key[1]):warnings.append('version_not_established');key=('review_unversioned',original,setting)
 if any(x.startswith('conflicting_')for x in warnings):key=('conflict',original,setting)
 # Display is chosen from observed complete names after grouping, independent
 # of result values, score, manufacturer priority or expected rank.
 base=text(n.replace('(',' ').replace(')',' '))
 for scale in setting_scales:
  if scale not in scales:base+=' '+scale
 for m in setting_modes:
  if m not in modes:base+=' '+m.title()
 display=base+(' ('+' | '.join(effort)+')'if effort else '')
 return {'key':key,'name':display,'setting':' | '.join(dict.fromkeys(conditions)),'proof':proof+[{'rule':'EXACT_PROTECTED_IDENTITY_TOKENS','tokens':key}],'warnings':warnings}

def project(data,canonical_registry=None):
 if data.get('dedup_policy'):raise ValueError('Use the original frozen source inputs; refusing to overwrite existing projection provenance')
 out=deepcopy(data);proposed={};by_key=defaultdict(set);evidence=defaultdict(list)
 for g in data['index']['groups']:
  for s in g['scores']:
   original=(s['model_canonical'],g.get('model_setting',''))
   evidence[original].extend({**r,'paper_id':g['paper_id'],'table_id':g['table_id'],'group_id':g['group_id']}for r in s.get('task_source_records',[]))
 for original,rs in sorted(evidence.items()):
  p=identify(*original,records=rs);proposed[original]=p;by_key[p['key']].add(original)
 # A same-table, same-condition disagreement is a review signal. Do not
 # globally merge this candidate identity cluster until its scope is resolved.
 conflicts=defaultdict(list)
 for g in data['index']['groups']:
  buckets=defaultdict(list)
  for s in g['scores']:buckets[proposed[s['model_canonical'],g.get('model_setting','')]['key']].append(s)
  for key,ss in buckets.items():
   if len({s['model_canonical']for s in ss})>1 and len({s['value_numeric']for s in ss})>1:
    conflicts[key].append({'group_id':g['group_id'],'paper_id':g['paper_id'],'table_id':g['table_id'],'metric':g['metric'],'labels_and_values':[(s['model_canonical'],s['value_numeric'])for s in ss]})
 registry=[];mapping={}
 for key,originals in sorted(by_key.items(),key=lambda kv:repr(kv[0])):
  originals=sorted(originals);attribute_conflict=any(w.startswith('conflicting_')for o in originals for w in proposed[o]['warnings']);blocked=key in conflicts or attribute_conflict
  candidates=sorted({proposed[o]['name']for o in originals},key=lambda x:(bool(re.match(r'(?i)^GPT[ -]',x))and not x.startswith('GPT-'),bool(re.search(r'\d(?:\.\d+)*(?:VL|Omni|Flash)',x,re.I)),bool(re.search(r'[()]',x)),len(x),x.casefold(),x))
  label=candidates[0];condition=proposed[originals[0]]['setting']
  key_id=hashlib.sha256(json.dumps(key,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
  previous=(canonical_registry or {}).get(key_id)
  if previous and not blocked:
   candidate=identify(previous['name'],previous['setting'])
   if candidate['key']==key:label=previous['name'];condition=previous['setting']
  for o in originals:
   mapping[o]=(o[0],o[1])if blocked else (label,condition)
  registry.append({'identity_key':key,'canonical_name':label,'canonical_condition':condition,'source_identities':[{'name':o[0],'setting':o[1]}for o in originals],'status':'REVIEW_SAME_SOURCE_CONFLICT'if key in conflicts else 'REVIEW_CONFLICTING_ATTRIBUTES'if attribute_conflict else 'REVIEW_VERSION_UNESTABLISHED'if key[0]=='review_unversioned'else 'FORMATTING_EQUIVALENT'if len(originals)>1 else 'UNCHANGED_OR_CONDITION_EXTRACTED','proof':[{'source_name':o[0],'source_setting':o[1],**proposed[o]}for o in originals],'same_source_conflicts':conflicts.get(key,[])})
  registry[-1]['identity_key_id']=key_id
  if len(originals)>1 or blocked or registry[-1]['status'].startswith('REVIEW_'):
   refs={}
   for o in originals:
    for r in evidence[o]:
     source=(r.get('paper_id'),r.get('table_id'),r.get('model_raw'))
     refs.setdefault(source,{'paper_id':r.get('paper_id'),'table_id':r.get('table_id'),'model_raw':r.get('model_raw'),'observation_ids':set(),'group_ids':set()})
     if r.get('observation_id'):refs[source]['observation_ids'].add(r['observation_id'])
     refs[source]['group_ids'].add(r['group_id'])
   registry[-1]['source_evidence']=[{**r,'observation_ids':sorted(r['observation_ids']),'group_ids':sorted(r['group_ids'])}for r in refs.values()]
 merged_cells=[];blocked_cells=[];unique_groups=[];duplicate_groups=[];seen={}
 projections=out.get('measurements',{}).get('groups',{})
 for g in out['index']['groups']:
  scores=[];buckets=defaultdict(list)
  old_setting=g.get('model_setting','');meta=projections.get(g['group_id']);allowed=set(meta['models'])if meta is not None else None
  for s in g['scores']:
   old=s['model_canonical'];name,condition=mapping[old,old_setting]
   s['dedup_original_model_name']=old;s['dedup_original_model_setting']=old_setting;s['model_canonical']=name;s['dedup_condition']=' | '.join(x for x in [condition,g.get('source_condition_key','')]if x)
   if allowed is None or old in allowed:buckets[name,s['dedup_condition']].append(s)
  for node,ss in buckets.items():
   values={s['value_numeric']for s in ss}
   if len(values)>1:blocked_cells.append({'group_id':g['group_id'],'node':node,'values':sorted(values)});continue
   row=deepcopy(ss[0]);row['dedup_original_labels']=sorted({s['dedup_original_model_name']for s in ss});row['observation_ids']=sorted({o for s in ss for o in s.get('observation_ids',[])});row['task_source_records']=[r for s in ss for r in s.get('task_source_records',[])];scores.append(row)
   if len(ss)>1:merged_cells.append({'group_id':g['group_id'],'node':node,'source_labels':row['dedup_original_labels'],'raw_value':row['value_numeric'],'observation_ids':row['observation_ids']})
  g['scores']=scores
  if meta is not None:meta['models']=sorted({s['model_canonical']for s in scores})
  # Same original cells plus the same semantic/condition coordinates only.
  # Identical numbers in other papers/tables are never proof of duplication.
  signature=(g['paper_id'],g['table_id'],g.get('row_key'),g['metric'],g['direction'],tuple(sorted((s['model_canonical'],s['dedup_condition'],s['value_numeric'],tuple(s.get('observation_ids',[])))for s in scores)))
  has_cells=bool(scores)and all(s.get('observation_ids')for s in scores)
  if has_cells and signature in seen:duplicate_groups.append({'kept_group_id':seen[signature],'duplicate_group_id':g['group_id']});continue
  if has_cells:seen[signature]=g['group_id']
  unique_groups.append(g)
 out['index']['groups']=unique_groups
 report={'policy':POLICY,'snapshot_id':data['snapshot_id'],'registry':registry,'merged_same_value_source_cells':merged_cells,'conflicting_source_cells_quarantined':blocked_cells,'duplicate_source_groups':duplicate_groups,'source_data_changed':False,'ranking_outcomes_used_for_identity':False}
 out['dedup_policy']=POLICY
 return out,report
