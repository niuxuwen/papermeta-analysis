"""Column-scoped direction checks. Never infer direction from a whole-table caption."""
import re

def check_direction(group):
    label=' '.join(str(group.get('metric') or '').casefold().split())
    up=bool(re.search(r'↑|\\uparrow',label));down=bool(re.search(r'↓|\\downarrow',label))
    hints=set()
    if up:hints.add('higher')
    if down:hints.add('lower')
    clean=re.sub(r'\\(?:up|down)arrow|[↑↓]','',label).strip()
    clean=re.sub(r'\s*\(%\)\s*$','',clean).strip()
    higher={ 'accuracy','precision','recall','f1','f1 score','f1-score','success rate','pass rate',
        'no-concern replies','no concern replies','no-concern reply rate','no concern reply rate'}
    lower={'error rate','word error rate','character error rate','wer','cer','rmse','mae','perplexity','collisions','collision count','mhqr'}
    if clean in higher:hints.add('higher')
    if clean in lower:hints.add('lower')
    context=str(group.get('metric_role_context') or '').casefold()
    # A distribution has several segments with different meanings. Its generic
    # heading is not an endpoint, even if another column has a direction arrow.
    ambiguous=(clean=='severity of replies' and 'no concern' in context and 'minor' in context and 'major' in context)
    actual=group.get('direction')
    if ambiguous or len(hints)>1:
        return dict(status='REVIEW_REQUIRED',reason='ambiguous_column_semantics',metric=group.get('metric'),actual=actual)
    if hints:
        expected=next(iter(hints))
        return dict(status='CONSISTENT' if actual==expected else 'CONFLICT',
            reason='column_direction_check',metric=group.get('metric'),actual=actual,expected=expected)
    return dict(status='UNVERIFIED',reason='no_column_direction_rule',metric=group.get('metric'),actual=actual)

def audit_directions(groups):
    events=[]
    for group in groups:
        check=check_direction(group)
        group['metric_direction_check']=check
        if check['status'] in ('CONFLICT','REVIEW_REQUIRED'):
            group.setdefault('source_quality',{}).update(eligible=False,reason=check['reason'])
            events.append(dict(group_id=group['group_id'],paper_id=group['paper_id'],**check))
    return events
