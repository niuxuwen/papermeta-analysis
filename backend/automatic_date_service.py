"""Checkpointed date-only review and publication; safe for recurring cron runs.

Own lock serializes reviewers. The score publisher lock protects feed capture and
date-only Git updates. Extraction queues and score sources are never changed.
"""
import argparse
from contextlib import contextmanager
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

from automatic_date_review import Reviewer, atomic, now


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a')as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:yield False;return
        try:yield True
        finally:fcntl.flock(f,fcntl.LOCK_UN)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb')as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def capture(project,state):
    publisher=project/'deployment/publication';feed=publisher/'feed/feed';dest=state/'input'
    dest.mkdir(parents=True,exist_ok=True)
    with locked(publisher/'publisher.lock')as acquired:
        if not acquired:return None
        pub=json.loads((feed/'publication.json').read_text())
        if pub.get('publisher')!='radar-publication-v1':raise ValueError('Unowned source publisher')
        target=dest/'source.json.gz';temp=target.with_suffix('.pending')
        if not target.exists()or sha(target)!=pub['source_sha256']:
            shutil.copyfile(feed/'source.json.gz',temp)
            if sha(temp)!=pub['source_sha256']:raise ValueError('Captured source hash mismatch')
            os.replace(temp,target)
        atomic(dest/'publication.json',pub)
    return pub


def publish(project,state):
    """Publish date evidence only, keeping source and score blobs byte-identical."""
    publisher=project/'deployment/publication';feed=publisher/'feed';directory=feed/'feed'
    envelope=json.loads((state/'registry.json').read_text())
    from recent_benchmarks.release_ledger import validate_registry,digest
    validate_registry(envelope['registry'])
    # Ignore heartbeat timestamps; meaningful source/decision changes publish.
    progress={k:v for k,v in envelope['progress'].items()if k!='updated_at'}
    fingerprint=digest({'registry':envelope['registry'],'progress':progress})
    with locked(publisher/'publisher.lock')as acquired:
        if not acquired:return {'status':'PUBLISHER_BUSY'}
        marker=json.loads((directory/'publication.json').read_text())
        if marker.get('publisher')!='radar-publication-v1':raise ValueError('Unowned live feed')
        protected=['source.json.gz','publication.json','task-inputs.json.gz','task-measurements.json.gz']
        hashes={p:sha(directory/p)for p in protected}
        if hashes['source.json.gz']!=marker['source_sha256']:raise ValueError('Live source hash differs from publication')
        previous=state/'last-published.json'
        if previous.exists()and json.loads(previous.read_text()).get('fingerprint')==fingerprint:
            return {'status':'UNCHANGED'}
        env={**os.environ,'GIT_TERMINAL_PROMPT':'0','RADAR_NETWORK_ENV':str(project/'deployment/network.env')}
        env['GIT_SSH_COMMAND']=shlex.join(['ssh','-o','BatchMode=yes','-o','IdentitiesOnly=yes',
            '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(publisher/'known_hosts'),
            '-o','ProxyCommand=python3 '+shlex.quote(str(publisher/'github_connect.py'))+' %h %p',
            '-i',str(publisher/'github_deploy_ed25519')])
        def git(*args,data=None):
            p=subprocess.run(['git','-C',str(feed),*args],env=env,input=data,capture_output=True,timeout=240)
            if p.returncode:raise RuntimeError('Date publication Git '+args[0]+' failed: '+p.stderr.decode(errors='replace')[-250:])
            return p.stdout
        remote=git('remote','get-url','origin').decode().strip()
        if remote!='ssh://git@ssh.github.com:443/niuxuwen/papermeta-analysis.git':raise ValueError('Unexpected publication repository')
        old=git('ls-remote','--heads','origin','refs/heads/live-data').decode().split()
        if not old:raise ValueError('Live feed missing')
        old=old[0];git('fetch','--depth=1','origin','live-data')
        upstream=json.loads(git('show','FETCH_HEAD:feed/publication.json'))
        if upstream!=marker:raise ValueError('Local source not current; wait for score publisher')
        git('fetch','--depth=1','origin','main');main=git('rev-parse','FETCH_HEAD').decode().strip()
        workflow=git('show',main+':.github/workflows/pages.yml')
        raw=json.dumps(envelope,ensure_ascii=False,separators=(',',':')).encode()
        # Reuse the score publisher credential scan without importing its main.
        import importlib.util
        spec=importlib.util.spec_from_file_location('date_publication_guard',publisher/'publish_live.py')
        guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard);guard.credential_scan(raw)
        packed=directory/'release-evidence.json.gz';temp=packed.with_suffix('.pending')
        temp.write_bytes(gzip.compress(raw,mtime=0));os.replace(temp,packed)
        wf=feed/'.github/workflows/pages.yml';wf.parent.mkdir(parents=True,exist_ok=True);wf.write_bytes(workflow)
        if hashes!={p:sha(directory/p)for p in protected}:raise ValueError('Score/source blobs changed during date publication')
        git('read-tree','--empty');git('add','--','feed','.github/workflows/pages.yml')
        tree=git('write-tree').decode().strip()
        commit=git('commit-tree',tree,data=('Automatic benchmark date evidence '+now()+'\n').encode()).decode().strip()
        git('push','--force-with-lease=refs/heads/live-data:'+old,'origin',commit+':refs/heads/live-data')
        result={'status':'PUBLISHED','fingerprint':fingerprint,'commit':commit,'published_at':now(),
                'review_snapshot_id':envelope['source_snapshot_id'],'score_snapshot_id':marker['snapshot_id'],
                'protected_blob_hashes':hashes}
        atomic(previous,result)
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True)
    p.add_argument('--state',type=Path,required=True);p.add_argument('--manual',type=Path,required=True)
    p.add_argument('--workers',type=int,default=8);p.add_argument('--research-limit',type=int,default=128)
    p.add_argument('--publish',action='store_true');p.add_argument('--resume-input',action='store_true')
    a=p.parse_args();a.state.mkdir(parents=True,exist_ok=True)
    def publish_checkpoint():
        if not a.publish:return
        try:result=publish(a.project,a.state)
        except Exception as e:
            result={'status':'PUBLICATION_FAILED_REVIEW_CONTINUES','at':now(),'error':type(e).__name__+':'+str(e)[:400]}
            atomic(a.state/'publication-error.json',result)
        print(json.dumps(result),flush=True)
    with locked(a.state/'worker.lock')as acquired:
        if not acquired:return
        atomic(a.state/'service-status.json',{'status':'RUNNING','pid':os.getpid(),'started_at':now()})
        try:
            pub=(json.loads((a.state/'input/publication.json').read_text())if a.resume_input else capture(a.project,a.state))
            if pub is None:
                atomic(a.state/'service-status.json',{'status':'WAITING_PUBLISHER_LOCK','checked_at':now()});return
            r=Reviewer(a.project,a.state,json.loads(a.manual.read_text(encoding='utf-8')))
            r.ingest(a.state/'input/source.json.gz',pub)
            r.run(workers=a.workers,priority=0)
            r.run(research=True,limit=a.research_limit,priority=0)
            publish_checkpoint()
            r.run(workers=a.workers)
            r.export()
            publish_checkpoint()
            r.run(research=True,limit=a.research_limit)
            publish_checkpoint()
            progress=r.export();r.db.close()
            atomic(a.state/'service-status.json',{'status':'CYCLE_COMPLETED','finished_at':now(),
                'snapshot_id':pub['snapshot_id'],'source_pass_complete':progress['source_pass_complete'],
                'all_first_dates_resolved':progress['all_first_dates_resolved']})
        except Exception as e:
            atomic(a.state/'service-status.json',{'status':'FAILED','failed_at':now(),'error':type(e).__name__+':'+str(e)[:400]})
            raise


if __name__=='__main__':main()
