import sqlite3, unittest
from recent_benchmarks.backlog_worker_repairs import repair_row


class CacheGateRepairTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value_json TEXT);
        CREATE TABLE jobs(arxiv_id TEXT PRIMARY KEY,status TEXT,phase TEXT,pipeline_stage TEXT
            CHECK(pipeline_stage IN ('','DOWNLOAD','PARSE','ANALYZE')),published_at TEXT,
            failure_json TEXT,attempts INTEGER,evidence_attempts INTEGER,screen_attempts INTEGER,
            download_attempts INTEGER,result_ready INTEGER,reservation_id TEXT,retry_at TEXT,
            last_error TEXT,updated_at TEXT,started_at TEXT,finished_at TEXT,run_name TEXT,paper_id TEXT);''')
        self.db.execute('INSERT INTO jobs VALUES('+','.join('?'*19)+')',
            ('2611.1','RETRY_EXHAUSTED','EXTRACT','ANALYZE','2026-11-01T00:00:00Z','{}',3,2,1,1,
             0,None,None,'RESPONSE_INVALID','old',None,'2026-11-16T19:13:50Z','live-p','p'))
        self.item={'arxiv_id':'2611.1','run_name':'live-p','paper_id':'p',
            'replay_at':'2026-11-16T18:55:23Z','audited_at':'2026-11-16T19:20:00Z',
            'reason':'ZERO_HTTP_OLD_REQUEST_RETRY_CLOSED'}
        self.now='2026-11-16T19:21:00Z'
    def tearDown(self):self.db.close()
    def test_exact_skip_is_refunded_once_with_backup(self):
        action,before=repair_row(self.db,self.item,self.now)
        self.assertEqual(action,'REQUEUED_OLD_CACHE_SKIP');self.assertEqual(before['attempts'],3)
        self.assertEqual(tuple(self.db.execute('SELECT status,attempts,evidence_attempts FROM jobs').fetchone()),('PENDING',2,1))
        self.assertEqual(repair_row(self.db,self.item,self.now)[0],'ALREADY_HANDLED')
    def test_running_success_and_changed_identity_are_preserved(self):
        for status in ['RUNNING','COMPLETE','PENDING','EXCLUDED']:
            self.db.execute('UPDATE jobs SET status=?',(status,))
            self.assertEqual(repair_row(self.db,self.item,self.now)[0],'STATE_CHANGED')
        self.db.execute("UPDATE jobs SET status='FAILED',paper_id='foreign'")
        self.assertEqual(repair_row(self.db,self.item,self.now)[0],'STATE_CHANGED')
    def test_later_failure_and_retry_deadline_are_preserved(self):
        self.db.execute("UPDATE jobs SET finished_at='2026-11-16T19:21:00Z'")
        self.assertEqual(repair_row(self.db,self.item,self.now)[0],'FINISH_CHANGED')
        self.db.execute("UPDATE jobs SET retry_at='2026-11-18T00:00:00Z'")
        self.assertEqual(repair_row(self.db,self.item,self.now)[0],'BACKOFF')


if __name__=='__main__':unittest.main()
