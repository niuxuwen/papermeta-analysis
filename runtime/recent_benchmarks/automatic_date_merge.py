"""Reconcile automatic date evidence with the preserved manual registry."""
from copy import deepcopy
from .release_ledger import digest,validate_registry


def merge_registries(manual,envelope,signatures):
    result=deepcopy(manual);validate_registry(result)
    if envelope.get('format')!='automatic-date-registry-v1':raise ValueError('Invalid automatic date registry envelope')
    automatic=envelope.get('registry');validate_registry(automatic)
    owners={(r['paper_id'],r['benchmark_id']):e for e in result['entities']for r in e.get('source_refs',[])}
    ids={e['entity_id']for e in result['entities']};accepted=skipped=0
    for incoming in automatic['entities']:
        row=deepcopy(incoming);kept=[]
        for ref in row.get('source_refs',[]):
            key=ref['paper_id'],ref['benchmark_id']
            if ref.get('source_signature')!=signatures.get(key):skipped+=1;continue
            previous=owners.get(key)
            if previous is None:kept.append(ref);continue
            # Known metric/subset dispositions and exact manual firstness are
            # protected; new automatic conflicts never overwrite them silently.
            if previous['decision']!='PENDING':skipped+=1;continue
            if row.get('kind')!='BENCHMARK' or previous.get('kind')not in {'BENCHMARK','UNKNOWN'}:skipped+=1;continue
            events=previous.setdefault('events',[]);known={digest(e)for e in events}
            events.extend(e for e in row.get('events',[])if digest(e)not in known)
            previous.setdefault('automatic_updates',[]).append({'policy':envelope.get('policy'),
                'source_signature':ref['source_signature'],'evidence_entity_id':row['entity_id']})
            if row['decision']=='EXISTING_OR_UPDATE':previous['decision']='EXISTING_OR_UPDATE'
            elif row['decision']=='CONFIRMED_NEW':
                previous.update(decision='CONFIRMED_NEW',kind='BENCHMARK',scope=row['scope'],firstness_evidence=row['firstness_evidence'])
            accepted+=1
        if not kept:continue
        row['source_refs']=kept
        if row['entity_id']in ids:raise ValueError('Automatic entity ID collision')
        ids.add(row['entity_id']);result['entities'].append(row);accepted+=len(kept)
        for ref in kept:owners[ref['paper_id'],ref['benchmark_id']]=row
    validate_registry(result)
    return result,{'accepted_source_updates':accepted,'stale_or_protected_source_updates':skipped}
