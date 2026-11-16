import os
import unittest
from unittest.mock import patch
from recent_benchmarks.registered_date_recovery import recover_date


class RegisteredDateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'RADAR_ALLOW_PAPER_DATE_FALLBACK': '1'}); self.env.start()
        self.b = {'name':'TestBench', 'novelty':'EXISTING', 'tests_llms':True, 'date_basis':'UNKNOWN'}
        self.p = {'publication_date':'2026-11-01T12:00:00Z'}
        self.start = '2026-02-17T00:00:00Z'; self.end = '2026-11-17T00:00:00Z'
    def tearDown(self): self.env.stop()
    def call(self, **kwargs): return recover_date(self.b,self.p,self.start,self.end,index=kwargs.get('index',{}))
    def test_datetime_window_objects_from_production_are_supported(self):
        from datetime import datetime
        r=recover_date(self.b,self.p,datetime.fromisoformat(self.start.replace('Z','+00:00')),datetime.fromisoformat(self.end.replace('Z','+00:00')),index={})
        self.assertEqual(r['eligibility'],'ELIGIBLE')

    def test_user_paper_fallback_preserves_existing_and_marks_provenance(self):
        r=self.call();self.assertEqual(r['eligibility'],'ELIGIBLE');self.assertEqual(r['novelty'],'EXISTING')
        self.assertTrue(r['date_is_fallback']);self.assertFalse(r['date_is_verified_first_public'])
        self.assertEqual(r['release_date'],self.p['publication_date'].replace('Z','+00:00'))
        self.assertEqual(self.b['date_basis'],'UNKNOWN')
    def test_disabled_feature_keeps_original_scientific_policy(self):
        with patch.dict(os.environ,{'RADAR_ALLOW_PAPER_DATE_FALLBACK':'0'}):self.assertIsNone(self.call())
    def test_known_old_date_wins_over_recent_paper(self):
        e={'benchmark_key':'k','benchmark_date':'2019-01-01','date_basis':'PRIMARY_PUBLIC_DATE'}
        r=self.call(index={'testbench':[e]});self.assertEqual(r['eligibility'],'EXCLUDED_DATE');self.assertFalse(r['date_is_fallback'])
    def test_non_llm_and_identity_conflict_cannot_be_admitted_by_dates(self):
        self.b['tests_llms']=False;self.assertIsNone(self.call())
        self.b['tests_llms']=True;self.b['identity_conflict']=True;self.assertIsNone(self.call())
    def test_known_exclusion_is_preserved(self):
        e={'benchmark_key':'k','excluded':True};self.assertIsNone(self.call(index={'testbench':[e]}))
    def test_ambiguous_name_is_not_resolved_by_date(self):
        es=[{'benchmark_key':'a'},{'benchmark_key':'b'}];self.assertIsNone(self.call(index={'testbench':es}))
    def test_missing_or_future_paper_date_does_not_invent_a_date(self):
        self.p['publication_date']=None;self.assertIsNone(self.call())
        self.p['publication_date']='2027-01-01T00:00:00Z';self.assertIsNone(self.call())
    def test_cached_paper_proxy_reuses_earlier_paper_timestamp(self):
        e={'benchmark_key':'k','benchmark_date':'2026-10-02','date_basis':'PAPER_PUBLICATION_FALLBACK','date_is_fallback':True,
           'date_evidence':[{'original_paper_timestamp':'2026-10-01T18:00:00Z'}]}
        self.assertEqual(self.call(index={'testbench':[e]})['release_date'],'2026-10-01T18:00:00+00:00')


class BacklogBudgetTicketTests(unittest.TestCase):
    def test_ticket_opens_one_failure_budget_without_invalidating_positive_results(self):
        import tempfile,json
        from pathlib import Path
        from recent_benchmarks.stage_checkpoints import StageCheckpoints
        with tempfile.TemporaryDirectory()as d:
            c=StageCheckpoints(Path(d),{'paper':{'paper_id':'p'}})
            positive=c._path('binding_batch',{'source':'same'});old=c._path('binding_failure_budget',{'source':'same'})
            (Path(d)/'user_backlog_retry.json').write_text(json.dumps({'version':1,'policy':'user-date-register-paper-fallback-20261117-v1','paper_id':'p','request_sha256':'a'*64}))
            new=c._path('binding_failure_budget',{'source':'same'})
            self.assertNotEqual(new,old);self.assertEqual(new,c._path('binding_failure_budget',{'source':'same'}))
            self.assertEqual(positive,c._path('binding_batch',{'source':'same'}))
    def test_foreign_paper_ticket_cannot_refund_current_paper(self):
        import tempfile,json
        from pathlib import Path
        from recent_benchmarks.stage_checkpoints import StageCheckpoints
        with tempfile.TemporaryDirectory()as d:
            c=StageCheckpoints(Path(d),{'paper':{'paper_id':'p'}});old=c._path('binding_failure_budget',{})
            (Path(d)/'user_backlog_retry.json').write_text(json.dumps({'version':1,'policy':'user-date-register-paper-fallback-20261117-v1','paper_id':'other','request_sha256':'a'*64}))
            self.assertEqual(old,c._path('binding_failure_budget',{}))


if __name__=='__main__':unittest.main()
