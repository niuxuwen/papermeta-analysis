"""Verified, version-pinned task contexts for automatically published snapshots."""
from collections import OrderedDict
import gzip,hashlib,json,re,threading,time
from urllib.parse import urljoin,urlparse
from urllib.request import Request,urlopen

class SnapshotUnavailable(ValueError):pass

class PublishedSnapshots:
    def __init__(self,base,factory,*,fetch=None,max_contexts=8,ttl=1200,clock=time.monotonic):
        parsed=urlparse(base)
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('A fixed HTTPS publication root is required')
        self.base=base.rstrip('/')+'/'
        self.factory,self.fetch,self.clock=factory,fetch or self._fetch,clock
        self.max_contexts,self.ttl=max_contexts,ttl
        self.entries=OrderedDict();self.latest=None;self.error=None;self.last_attempt=-float('inf')
        self.lock=threading.RLock();self.loading=threading.Lock()

    @staticmethod
    def _fetch(url,limit):
        with urlopen(Request(url,headers={'Cache-Control':'no-cache','User-Agent':'PaperMeta-Task-Snapshot/1'}),timeout=25)as r:
            data=r.read(limit+1)
        if len(data)>limit:raise SnapshotUnavailable('publication_too_large')
        return data

    def refresh(self,*,wait=False,min_interval=0):
        acquired=self.loading.acquire(timeout=8)if wait else self.loading.acquire(blocking=False)
        if not acquired:return
        try:
            if self.clock()-self.last_attempt<min_interval:return
            self.last_attempt=self.clock()
            # Pages/CDN may cache this mutable pointer even when its immutable
            # generation assets are already available. Do not wait ten minutes.
            manifest=json.loads(self.fetch(urljoin(self.base,'snapshot/current.json')+'?task-service='+str(int(time.time())),1024*1024))
            sid=manifest.get('snapshot_id','')
            if not re.fullmatch('[a-f0-9]{24}',sid):raise SnapshotUnavailable('invalid_publication_identity')
            with self.lock:
                if sid in self.entries:self.latest=sid;self.error=None;return
            item=manifest.get('task_inputs')or{}
            if item.get('path')!=f'snapshot/{sid}/task-inputs.json.gz' or item.get('snapshot_id')!=sid:
                raise SnapshotUnavailable('task_publication_pending')
            size=item.get('bytes');sha=item.get('sha256','')
            if type(size)is not int or not 0<size<=32*1024*1024 or not re.fullmatch('[a-f0-9]{64}',sha):
                raise SnapshotUnavailable('invalid_task_descriptor')
            raw=self.fetch(urljoin(self.base,item['path']),size)
            if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=sha:raise SnapshotUnavailable('task_publication_integrity')
            data=json.loads(gzip.decompress(raw))
            if (data.get('format')!='radar-task-inputs-v1' or data.get('snapshot_id')!=sid
                or data.get('task_method_version')not in (8,9,10) or data.get('measurements',{}).get('snapshot_id')!=sid):
                raise SnapshotUnavailable('task_publication_identity_mismatch')
            with self.lock:
                now=self.clock()
                for old,(context,touched)in list(self.entries.items()):
                    if old!=self.latest and now-touched>=self.ttl and not context.busy():
                        context.close();del self.entries[old]
                if len(self.entries)>=self.max_contexts:raise SnapshotUnavailable('task_snapshot_capacity')
            context=self.factory(data)
            with self.lock:self.entries[sid]=(context,self.clock());self.latest=sid;self.error=None
        except Exception as exc:
            self.error=str(exc)if isinstance(exc,SnapshotUnavailable)else 'publication_temporarily_unavailable'
        finally:self.loading.release()

    def get(self,sid=None):
        with self.lock:
            sid=sid or self.latest
            if sid not in self.entries:raise SnapshotUnavailable(self.error or 'task_snapshot_not_loaded')
            context,_=self.entries[sid];self.entries[sid]=(context,self.clock());self.entries.move_to_end(sid)
            return context

    def close(self):
        with self.lock:
            for context,_ in self.entries.values():context.close()
            self.entries.clear()
