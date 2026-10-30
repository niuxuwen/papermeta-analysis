import gzip,hashlib,json,unittest
from task_snapshots import PublishedSnapshots,SnapshotUnavailable

class Context:
    def __init__(self,data):self.sid=data['snapshot_id'];self.closed=False;self.running=False
    def close(self):self.closed=True
    def busy(self):return self.running

class PublishedSnapshotsTests(unittest.TestCase):
    def setUp(self):self.sid='a'*24;self.corrupt=False;self.path=None;self.now=0
    def fetch(self,url,limit):
        raw=gzip.compress(json.dumps({'format':'radar-task-inputs-v1','snapshot_id':self.sid,
            'task_method_version':8,'measurements':{'snapshot_id':self.sid}}).encode(),mtime=0)
        if url.endswith('snapshot/current.json'):
            return json.dumps({'snapshot_id':self.sid,'task_inputs':{'snapshot_id':self.sid,
                'path':self.path or f'snapshot/{self.sid}/task-inputs.json.gz','bytes':len(raw),
                'sha256':hashlib.sha256(raw).hexdigest()}}).encode()
        return b'broken'if self.corrupt else raw
    def store(self,**kw):return PublishedSnapshots('https://cowhors.com/',Context,fetch=self.fetch,clock=lambda:self.now,**kw)
    def test_new_publication_does_not_replace_an_active_old_version(self):
        s=self.store();s.refresh();first=s.get();first.running=True
        self.sid='b'*24;s.refresh()
        self.assertEqual(s.get().sid,self.sid);self.assertIs(s.get('a'*24),first);self.assertFalse(first.closed)
    def test_corruption_or_external_path_cannot_replace_previous_verified_inputs(self):
        s=self.store();s.refresh();first=s.get();self.sid='b'*24;self.corrupt=True;s.refresh()
        self.assertIs(s.get(),first);self.assertEqual(s.error,'task_publication_integrity')
        self.corrupt=False;self.path='https://evil.test/input';s.refresh();self.assertIs(s.get(),first)
        with self.assertRaises(SnapshotUnavailable):s.get(self.sid)
    def test_capacity_and_live_jobs_are_preserved(self):
        s=self.store(max_contexts=2,ttl=10);s.refresh();old=s.get();old.running=True
        self.sid='b'*24;s.refresh();self.now=20;self.sid='c'*24;s.refresh()
        self.assertEqual(s.error,'task_snapshot_capacity');self.assertFalse(old.closed)
        old.running=False;s.refresh();self.assertTrue(old.closed);self.assertEqual(s.get().sid,self.sid)
    def test_non_https_publication_roots_are_refused(self):
        for url in ('http://cowhors.com/','https://user:secret@cowhors.com/','https://cowhors.com/?secret=x'):
            with self.assertRaises(ValueError):PublishedSnapshots(url,Context)

if __name__=='__main__':unittest.main()
