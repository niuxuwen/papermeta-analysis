import hashlib
import json
import sqlite3
import unittest
from replay_backlog_request import replay_row


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value_json TEXT);
        CREATE TABLE jobs(arxiv_id TEXT PRIMARY KEY,status TEXT,phase TEXT,pipeline_stage TEXT CHECK(pipeline_stage IN ('','DOWNLOAD','PARSE','ANALYZE')),published_at TEXT,
        failure_json TEXT,attempts INTEGER,evidence_attempts INTEGER,screen_attempts INTEGER,download_attempts INTEGER,
        result_ready INTEGER,reservation_id TEXT,retry_at TEXT,last_error TEXT,updated_at TEXT,started_at TEXT,finished_at TEXT);''')
        self.failure=json.dumps({'kind':'REQUEST_INVALID','stage':'ANALYSIS'})
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('2611.12345','FAILED','EXTRACT','ANALYZE','2026-11-01T00:00:00Z',self.failure,3,3,1,1,0,None,None,'REQUEST_INVALID','old',None,'old'))
        self.item={'arxiv_id':'2611.12345','route':'ONE_USER_REQUESTED_TECHNICAL_REPLAY',
            'original_failure_sha256':hashlib.sha256(self.failure.encode()).hexdigest()}
        self.now='2026-11-17T00:00:00Z';self.start='2026-09-18T00:00:00Z'
    def tearDown(self):self.db.close()
    def test_exact_row_gets_one_opportunity_with_original_backup(self):
        status,old=replay_row(self.db,self.item,self.now,self.start);self.assertEqual(status,'REQUEUED')
        self.assertEqual(old['attempts'],3);r=dict(self.db.execute('SELECT * FROM jobs').fetchone())
        self.assertEqual((r['status'],r['attempts'],r['evidence_attempts']),('PENDING',2,2))
        self.assertIsNone(r['failure_json']);self.assertEqual(replay_row(self.db,self.item,self.now,self.start)[0],'ALREADY_REPLAYED')
    def test_healthy_or_active_rows_are_not_reopened(self):
        for status in ['COMPLETE','EXCLUDED','RUNNING','PENDING']:
            self.db.execute('UPDATE jobs SET status=?',(status,));self.assertEqual(replay_row(self.db,self.item,self.now,self.start)[0],'NO_LONGER_TERMINAL')
    def test_screen_replay_uses_empty_stage_as_required_by_production_schema(self):
        self.db.execute("UPDATE jobs SET phase='SCREEN',pipeline_stage=''")
        status,_=replay_row(self.db,self.item,self.now,self.start)
        self.assertEqual(status,'REQUEUED');self.assertEqual(self.db.execute('SELECT phase,pipeline_stage FROM jobs').fetchone()[:],('SCREEN',''))

    def test_changed_failure_requires_new_audit(self):
        self.item['original_failure_sha256']='changed';self.assertEqual(replay_row(self.db,self.item,self.now,self.start)[0],'FAILURE_CHANGED_SINCE_AUDIT')
    def test_future_retry_and_expired_paper_are_preserved(self):
        self.db.execute("UPDATE jobs SET retry_at='2026-11-18T00:00:00Z'");self.assertEqual(replay_row(self.db,self.item,self.now,self.start)[0],'RETRY_DEADLINE_NOT_REACHED')
        self.db.execute("UPDATE jobs SET retry_at=NULL,published_at='2026-01-01T00:00:00Z'");self.assertEqual(replay_row(self.db,self.item,self.now,self.start)[0],'OUTSIDE_PAPER_WINDOW')
    def test_missing_cached_source_restarts_download_with_bounded_budget(self):
        self.item['resume_stage']='DOWNLOAD';replay_row(self.db,self.item,self.now,self.start)
        r=self.db.execute('SELECT pipeline_stage,download_attempts FROM jobs').fetchone();self.assertEqual(tuple(r),('DOWNLOAD',0))


if __name__=='__main__':unittest.main()
