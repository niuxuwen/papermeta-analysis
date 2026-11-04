"""Cross-paper dataset identities, separate from release/score/source identities.

No fuzzy joins, score-vector matching, or transitive alias union. A registry
documents known aliases; other distinctive names can match exactly, with
explicit ambiguity guards. Scope variants never share a directory entry.
"""
from collections import defaultdict, Counter
from hashlib import sha256
import json
import re
import unicodedata
from urllib.parse import urlsplit

VERSION = 'benchmark-entities-v1'
KNOWN = [
    ('MMLU', ['MMLU', 'Massive Multitask Language Understanding'], 'https://github.com/hendrycks/test'),
    ('MMLU-Pro', ['MMLU-Pro', 'MMLU Pro', 'MMLU_PRO'], 'https://github.com/TIGER-AI-Lab/MMLU-Pro'),
    ('GSM8K', ['GSM8K', 'Grade School Math 8K'], 'https://github.com/openai/grade-school-math'),
    ('HumanEval', ['HumanEval', 'Human Eval', 'Human-Eval'], 'https://github.com/openai/human-eval'),
    ('MATH', ['MATH'], 'https://github.com/hendrycks/math'),
]
GENERIC = {'overall', 'average', 'avg', 'total', 'score', 'accuracy', 'acc', 'f1', 'precision',
    'recall', 'benchmark', 'dataset', 'test', 'train', 'dev', 'validation', 'math', 'reasoning',
    'english', 'chinese', 'qa', 'mcq', 'arc', 'all', 'none', 'unknown', '名称待核验', '名称待核实', '名称待确认'}

def key(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    value = value.translate(str.maketrans({'–':'-', '—':'-', '‑':'-', '−':'-'}))
    return re.sub(r'[\s_\-]+', '', value).strip()

def identifier(prefix, value):
    return prefix + sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]

def source_key(row):
    return json.dumps([row['paper_id'], row['benchmark_id']], ensure_ascii=False, separators=(',', ':'))

def resources(row):
    items = (row.get('enrichment') or {}).get('assets', {}).get('items', [])
    result = set()
    for item in items:
        if not isinstance(item, dict) or not item.get('evidence_quote'):
            continue
        if item.get('kind', '').lower() not in {'dataset', 'repository', 'code', 'project', 'homepage'}:
            continue
        try:
            url = urlsplit(item.get('url', ''))
            path = re.sub(r'\.git$', '', url.path.rstrip('/'))
            if url.scheme not in {'http', 'https'} or not url.hostname or url.username or not path:
                continue
            if url.hostname.lower() in {'arxiv.org', 'export.arxiv.org', 'doi.org'}:
                continue
            # Preserve repository/dataset identity; never use a publisher domain alone.
            if url.hostname.lower() in {'github.com', 'huggingface.co'} and path.count('/') < 2:
                continue
            result.add(url.hostname.lower() + path + ('?' + url.query if url.query else ''))
        except ValueError:
            pass
    return sorted(result)

def parse_scope(row):
    name = ' '.join(str(row.get('benchmark_name') or '').split())
    scope = {f: str(row[f]).strip().casefold() for f in
        ('version', 'benchmark_version', 'subset', 'split', 'language') if row.get(f)}
    if 'benchmark_version' in scope:
        scope.setdefault('version', scope.pop('benchmark_version'))
    if 'version' in scope:
        scope['version'] = re.sub(r'^v(?:ersion\s*)?(?=\d)', '', scope['version'])
    if 'language' in scope:
        scope['language'] = {'english':'en','chinese':'zh'}.get(scope['language'],scope['language'])
    # Strip only explicit trailing versions; intrinsic names such as AMC23,
    # MATH-500, MMLU-Pro and HumanEval+ retain their dataset identity.
    version = re.search(r'(?i)(?:[\s_-]+|\()v(?:ersion\s*)?(\d+(?:\.\d+)*)(?:\))?$', name)
    if version:
        scope['version'] = version[1]
        name = name[:version.start()].strip()
    semver = re.search(r'\s+(\d+\.\d+(?:\.\d+)*)$', name)
    if semver:
        scope['version'] = semver[1]
        name = name[:semver.start()].strip()
    annual = re.fullmatch(r'(?i)(AIME|AMC)[\s_-]*(\d{2}|20\d{2})', name)
    if annual:
        name = annual[1].upper();scope['year'] = annual[2]
    tagged = re.search(r'(?i)\s*\((english|chinese|en|zh|test|train|dev|validation|[^()]+ subset)\)$', name)
    if tagged:
        label = tagged[1].casefold()
        if label in {'english','chinese','en','zh'}:
            scope['language'] = {'english':'en','chinese':'zh'}.get(label,label)
        elif label in {'test','train','dev','validation'}:
            scope['split'] = label
        else:
            scope['subset'] = re.sub(r' subset$', '', label)
        name = name[:tagged.start()].strip()
    return name, scope

def build_registry(catalog):
    known = {key(alias): (name, url) for name, aliases, url in KNOWN for alias in aliases}
    prepared, buckets = [], defaultdict(list)
    for row in catalog:
        name, scope = parse_scope(row)
        token = key(name)
        registered = known.get(token)
        audit = (row.get('name_audit') or {}).get('status')
        reason = None
        if audit in {'REVIEW_REQUIRED', 'DESCRIPTIVE'} or not token or name.startswith('名称待'):
            reason = 'UNRESOLVED_NAME'
        elif (token in GENERIC or (len(token) < 4 and 'year' not in scope)) and not registered:
            reason = 'GENERIC_OR_SHORT_NAME'
        elif token == 'math' and name != 'MATH':
            reason = 'GENERIC_OR_SHORT_NAME'
        elif not registered and not (re.search(r'[A-Z]{2}|[a-z][A-Z]|(?i:bench)', name) or resources(row)):
            reason = 'DESCRIPTIVE_OR_UNSUPPORTED_NAME'
        if row.get('identity_conflict') is True:
            reason = 'SOURCE_IDENTITY_CONFLICT'
        record = {'row': row, 'name': name, 'key': token, 'scope': scope,
                  'registered': registered, 'resources': resources(row), 'reason': reason}
        prepared.append(record)
        if not reason:
            buckets[token].append(record)
    # Proof-backed full-name/acronym links for the long tail. Complete linkage
    # prevents a shared toolkit repository or broad alias list joining datasets.
    resource_buckets = defaultdict(list)
    for i, record in enumerate(prepared):
        if record['reason'] or record['registered']:
            continue
        record['aliases'] = {record['key'], *(key(a) for a in record['row'].get('benchmark_aliases') or [])} - GENERIC
        selectors = tuple(re.findall(r'(?i)(?:\d+(?:\.\d+)*|(?<![a-z])(?:pro|plus|hard|easy|lite|mini|verified)(?![a-z]))', record['name'].casefold()))
        record['signature'] = (json.dumps(record['scope'], sort_keys=True), selectors, record['name'].count('+'))
        for resource in record['resources']:
            for alias in record['aliases']:
                if len(alias) >= 4:
                    resource_buckets[(resource, alias, record['signature'])].append(i)
    owners = list(range(len(prepared)));clusters = {i:{i} for i in range(len(prepared))}
    for bucket in sorted(resource_buckets):
        candidates = sorted(resource_buckets[bucket], key=lambda i:source_key(prepared[i]['row']))
        for i in candidates:
            for j in candidates:
                left, right = owners[i], owners[j]
                if left == right:
                    continue
                if all(prepared[a]['signature']==prepared[b]['signature'] and
                       set(prepared[a]['resources']) & set(prepared[b]['resources']) and
                       prepared[a]['aliases'] & prepared[b]['aliases']
                       for a in clusters[left] for b in clusters[right]):
                    for member in clusters[right]:owners[member]=left
                    clusters[left].update(clusters.pop(right))
    resource_names = {}
    for indices in clusters.values():
        if len({prepared[i]['key'] for i in indices}) < 2:
            continue
        canonical = min((prepared[i]['name'] for i in indices), key=lambda n:(len(n), n.casefold(), n))
        for i in indices:resource_names[i] = canonical
    # An alias can link to a registered primary, but cannot become a bridge
    # joining unrelated registered datasets (e.g. broad comparison-table aliases).
    alias_targets = defaultdict(set)
    for record in prepared:
        if record['reason'] or not record['registered']:
            continue
        proof = record['row'].get('identity_resolution') or {}
        if proof.get('relation') != 'SAME':
            continue
        for alias in record['row'].get('benchmark_aliases') or []:
            token = key(alias)
            if len(token) >= 4 and token not in GENERIC:
                alias_targets[token].add(record['registered'][0])
    entities, variants, mappings = {}, {}, []
    for position, record in enumerate(prepared):
        row, name, token = record['row'], record['name'], record['key']
        reason, match = record['reason'], 'EXACT_DISTINCTIVE_NAME'
        registration = record['registered']
        if not registration and not reason and len(alias_targets.get(token, ())) == 1:
            target = next(iter(alias_targets[token]))
            registration = next((n, u) for n, _, u in KNOWN if n == target)
            match = 'SOURCE_DECLARED_ALIAS'
        if registration:
            canonical, anchor = registration
            entity_key = ['registered', key(canonical)]
            match = 'REGISTERED_ALIAS' if match != 'SOURCE_DECLARED_ALIAS' else match
        else:
            members = [m for m in buckets.get(token, []) if m['scope'] == record['scope']]
            new_owners = {m['row'].get('paper_id') for m in members
                if m['row'].get('date_basis') == 'PAPER_V1_PROXY' and m['row'].get('eligibility') == 'ELIGIBLE'}
            resource_sets = {tuple(m['resources']) for m in members if m['resources']}
            # A repeated new name with different introductions/resources is an
            # unresolved homonym, never forcibly collapsed by spelling.
            if not reason and (len(new_owners) > 1 or len(resource_sets) > 1):
                reason = 'AMBIGUOUS_HOMONYM'
            canonical = min((m['name'] for m in members), key=lambda s: (len(s), s.casefold(), s)) if members else name
            anchor = None
            entity_key = ['name', token]
            if position in resource_names and not reason:
                canonical = resource_names[position]
                entity_key = ['name', key(canonical)]
                match = 'SHARED_RESOURCE_AND_DECLARED_ALIAS'
        mapping = {'paper_id': row['paper_id'], 'benchmark_id': row['benchmark_id'],
            'source_name': row.get('benchmark_name'), 'entity_id': None, 'variant_id': None,
            'canonical_name': canonical, 'scope': record['scope'], 'status': reason or 'RESOLVED',
            'match_basis': match if not reason else None}
        if not reason:
            eid = identifier('benchmark-entity-', entity_key)
            vid = identifier('benchmark-variant-', [eid, record['scope']])
            mapping.update(entity_id=eid, variant_id=vid)
            if eid not in entities:
                entities[eid] = {'entity_id': eid, 'canonical_name': canonical, 'reference_url': anchor,
                    'match_basis': match, 'aliases': set(), 'sources': [], 'variants': set()}
            entity = entities[eid]
            entity['aliases'].add(row.get('benchmark_name', name))
            # Only aliases which normalize to this same identity are flattened.
            for alias in row.get('benchmark_aliases') or []:
                if key(alias) == token or (known.get(key(alias)) or (None,))[0] == canonical:
                    entity['aliases'].add(alias)
            ref = {'paper_id': row['paper_id'], 'benchmark_id': row['benchmark_id']}
            entity['sources'].append(ref);entity['variants'].add(vid)
            variants.setdefault(vid, {'variant_id': vid, 'entity_id': eid, 'scope': record['scope'], 'sources': []})['sources'].append(ref)
        mappings.append(mapping)
    for entity in entities.values():
        entity['aliases'] = sorted(entity['aliases'])
        entity['variants'] = sorted(entity['variants'])
        entity['sources'] = sorted(entity['sources'], key=source_key)
    for variant in variants.values():
        variant['sources'] = sorted(variant['sources'], key=source_key)
    unresolved = Counter(m['status'] for m in mappings if m['status'] != 'RESOLVED')
    return {'version': VERSION, 'entities': sorted(entities.values(), key=lambda e:e['entity_id']),
        'variants': sorted(variants.values(), key=lambda v:v['variant_id']),
        'mappings': sorted(mappings, key=source_key),
        'statistics': {'source_records': len(catalog), 'resolved_entities': len(entities),
            'resolved_variants': len(variants), 'resolved_source_records': sum(m['status']=='RESOLVED' for m in mappings),
            'unresolved_source_records': sum(unresolved.values()), 'unresolved_reasons': dict(sorted(unresolved.items())),
            'registered_entities': sum(e['reference_url'] is not None for e in entities.values()),
            'count_scope': 'RESOLVED_CATALOG_ENTITIES; unresolved names are excluded, not assumed unique'}}
