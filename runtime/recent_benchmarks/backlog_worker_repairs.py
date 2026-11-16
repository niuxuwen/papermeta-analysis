"""Consume an exact, audited cache-gate repair on the queue owner's worker host."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import sqlite3
from pathlib import Path

POLICY='backlog-old-cache-gate-skips-20261117-v1'


def repair_row(db, item, now):
    marker=POLICY+':'+item['arxiv_id']
    if db.execute('SELECT 1 FROM meta WHERE key=?',(marker,)).fetchone():return 'ALREADY_HANDLED',None
    row=db.execute('SELECT * FROM jobs WHERE arxiv_id=?',(item['arxiv_id'],)).fetchone()
    if row is None:return 'MISSING',None
    row=dict(row)
    if (row['status'] not in {'FAILED','RETRY_EXHAUSTED'} or row['run_name']!=item['run_name']
            or row['paper_id']!=item['paper_id'] or row['phase']!='EXTRACT'
            or row.get('last_error') not in {'RESPONSE_INVALID','RESPONSE_BUDGET'}):return 'STATE_CHANGED',None
    first=(datetime.fromisoformat(now.replace('Z','+00:00'))-timedelta(days=60)).isoformat().replace('+00:00','Z')
    if not first<=row['published_at']<now:return 'OUTSIDE_WINDOW',None
    if row.get('retry_at') and row['retry_at']>now:return 'BACKOFF',None
    if not item['replay_at']<=str(row.get('finished_at')or'')<=item['audited_at']:return 'FINISH_CHANGED',None
    if item.get('reason')!='ZERO_HTTP_OLD_REQUEST_RETRY_CLOSED':return 'UNAUTHORIZED_REASON',None
    db.execute("""UPDATE jobs SET status='PENDING',pipeline_stage='ANALYZE',
        attempts=MAX(0,attempts-1),evidence_attempts=MAX(0,evidence_attempts-1),
        result_ready=0,reservation_id=NULL,retry_at=NULL,last_error='',failure_json=NULL,
        updated_at=?,started_at=NULL,finished_at=NULL WHERE arxiv_id=?""",(now,item['arxiv_id']))
    db.execute('INSERT INTO meta(key,value_json) VALUES(?,?)',(marker,json.dumps({'at':now,'reason':item['reason'],
        'one_actual_attempt_only':True,'previous_failure':row.get('failure_json')})))
    return 'REQUEUED_OLD_CACHE_SKIP',row


def apply_requested_repairs():
    # This is called by analysis subprocesses, so SQLite is opened on its owner
    # host. The controller never writes the shared-host WAL database remotely.
    if os.getenv('RADAR_ALLOW_PAPER_DATE_FALLBACK')!='1':return
    root=Path(__file__).resolve().parent.parent
    out=root/'deployment/backlog-process-20261117'
    request=out/'old-cache-skips-request.json'
    receipt=out/'old-cache-skips-result.json'
    if not request.exists() or receipt.exists():return
    try:
        import fcntl
        from .live_store import LiveStore
        with (out/'old-cache-skips.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
            if receipt.exists():return
            plan=json.loads(request.read_text())
            if plan.get('policy')!=POLICY or len(plan.get('papers',[]))>64:return
            now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
            results=[];before=[]
            store=LiveStore(root/'data/service/queue.sqlite')
            with store._connection(write=True) as db:
                db.execute('BEGIN IMMEDIATE')
                for item in plan['papers']:
                    run=root/'data/runs'/item['run_name']
                    log=root/'data/logs'/(item['run_name']+'.log')
                    ledger=run/'evidence'/(item['paper_id']+'.json')
                    safe=(run.resolve().parent==(root/'data/runs').resolve()
                        and hashlib.sha256(log.read_bytes()).hexdigest()==item['log_sha256']
                        and hashlib.sha256(ledger.read_bytes()).hexdigest()==item['ledger_sha256'])
                    action,old=repair_row(db,item,now) if safe else ('ARTIFACT_CHANGED',None)
                    results.append({'arxiv_id':item['arxiv_id'],'result':action})
                    if old:before.append(old)
                if before:
                    backup=out/'old-cache-skips-queue-before.json'
                    with backup.open('w') as f:
                        os.chmod(backup,0o600);json.dump(before,f);f.flush();os.fsync(f.fileno())
            temp=receipt.with_suffix('.tmp')
            temp.write_text(json.dumps({'at':now,'policy':POLICY,'per_paper':results,
                'requeued':len(before),'global_queue_reset':False},indent=2))
            temp.replace(receipt)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        # Optional recovery must not fail another paper's authorized analysis.
        return
