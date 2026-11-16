"""Consume an exact, audited user backlog request once on the worker host.

Run before LiveService starts. It does not reset scientific failures globally.
Each selected terminal row gets at most one additional attempt, with its former
row preserved and an atomic per-paper policy marker preventing a second refund.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

POLICY = 'user-date-register-paper-fallback-20261117-v1'


def replay_row(db, item, now, start):
    marker = 'user_backlog_replay:' + POLICY + ':' + item['arxiv_id']
    if db.execute('SELECT 1 FROM meta WHERE key=?', (marker,)).fetchone():
        return 'ALREADY_REPLAYED', None
    row = db.execute('SELECT * FROM jobs WHERE arxiv_id=?', (item['arxiv_id'],)).fetchone()
    if row is None:
        return 'MISSING_JOB', None
    row = dict(row)
    if row['status'] not in {'FAILED','RETRY_EXHAUSTED','REVIEW'}:
        return 'NO_LONGER_TERMINAL', None
    if not start <= row['published_at'] < now:
        return 'OUTSIDE_PAPER_WINDOW', None
    if hashlib.sha256((row.get('failure_json') or '').encode()).hexdigest() != item['original_failure_sha256']:
        return 'FAILURE_CHANGED_SINCE_AUDIT', None
    if row.get('retry_at') and row['retry_at'] > now:
        return 'RETRY_DEADLINE_NOT_REACHED', None
    route = item['route']
    if route not in {'DATE_REGISTER_RECOVERY','ONE_USER_REQUESTED_TECHNICAL_REPLAY'}:
        return 'UNAUTHORIZED_ROUTE', None
    phase = 'SCREEN' if row['phase'] == 'SCREEN' else 'EXTRACT'
    stage = '' if phase == 'SCREEN' else item.get('resume_stage') or row.get('pipeline_stage') or 'ANALYZE'
    # SQL fields are fixed; only exact audited IDs and states are changed.
    db.execute('''UPDATE jobs SET status='PENDING', phase=?, pipeline_stage=?,
        attempts=MAX(0,attempts-1), evidence_attempts=CASE WHEN ? THEN MAX(0,evidence_attempts-1) ELSE evidence_attempts END,
        screen_attempts=CASE WHEN ? THEN MAX(0,screen_attempts-1) ELSE screen_attempts END,
        download_attempts=CASE WHEN ? THEN MAX(0,download_attempts-1) ELSE download_attempts END,
        result_ready=0,reservation_id=NULL,retry_at=NULL,last_error='',failure_json=NULL,
        updated_at=?,started_at=NULL,finished_at=NULL WHERE arxiv_id=?''',
        (phase,stage,int(phase!='SCREEN'),int(phase=='SCREEN'),int(stage=='DOWNLOAD'),now,item['arxiv_id']))
    receipt={'at':now,'route':route,'one_additional_attempt':True,'previous_status':row['status'],
        'previous_failure_sha256':item['original_failure_sha256'],'original_attempts':row['attempts'],
        'source_sha256':item.get('source_sha256'),'stage':stage}
    db.execute('INSERT INTO meta(key,value_json) VALUES(?,?)',(marker,json.dumps(receipt)))
    return 'REQUEUED', row


def main():
    import fcntl
    root=Path.cwd(); out=root/'deployment/backlog-process-20261117'
    request=json.loads((out/'request.json').read_text())
    if request.get('policy') != POLICY or request.get('one_additional_attempt_per_paper') is not True:
        raise ValueError('Invalid bounded backlog request')
    if os.getenv('RADAR_ALLOW_PAPER_DATE_FALLBACK') != '1':
        raise RuntimeError('Explicit user date-fallback configuration is required')
    sys.path.insert(0,str(root))
    from recent_benchmarks.live_store import LiveStore
    from recent_benchmarks.registered_date_recovery import POLICY as active_policy
    if active_policy != POLICY:raise RuntimeError('Date recovery code is not deployed')
    now=datetime.now(timezone.utc); end=now.isoformat().replace('+00:00','Z')
    start=(now-timedelta(days=60)).isoformat().replace('+00:00','Z')
    ledger=[]; backups=[]
    request_sha256=hashlib.sha256((out/'request.json').read_bytes()).hexdigest()
    with (root/'data/service/.run.lock').open('a')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        store=LiveStore(root/'data/service/queue.sqlite')
        with store._connection(write=True)as db:
            db.execute('BEGIN IMMEDIATE')
            for item in request['papers']:
                route,before=replay_row(db,item,end,start)
                ledger.append({'arxiv_id':item['arxiv_id'],'route':item['route'],'result':route})
                if before:
                    backups.append(before)
                    run=root/'data/runs'/before['run_name']
                    if not run.resolve().is_relative_to((root/'data/runs').resolve()):raise ValueError('Unsafe saved run path')
                    ticket={'version':1,'policy':POLICY,'paper_id':before['paper_id'],
                        'request_sha256':request_sha256,'one_additional_attempt':True}
                    path=run/'user_backlog_retry.json';temp=path.with_suffix('.pending')
                    temp.write_text(json.dumps(ticket));temp.replace(path)
            # A rollback restores the DB if backup persistence fails.
            backup=out/'replay-queue-before.json'
            if backups:
                with backup.open('w',encoding='utf-8')as f:
                    os.chmod(backup,0o600);json.dump(backups,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    result={'at':end,'policy':POLICY,'requested':len(request['papers']),
        'requeued':sum(e['result']=='REQUEUED'for e in ledger),'per_paper':ledger,
        'one_additional_attempt_per_paper':True,'global_queue_reset':False,'paper_days':60}
    target=out/('replay-result.json' if result['requeued'] or not(out/'replay-result.json').exists()else'replay-already-consumed.json');tmp=target.with_suffix('.pending');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2));tmp.replace(target)
    print('Audited old-paper replay queued:',result['requeued'],flush=True)


if __name__=='__main__':main()
