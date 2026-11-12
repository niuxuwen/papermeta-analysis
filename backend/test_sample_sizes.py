import unittest
from copy import deepcopy
from sample_sizes import annotate, entries

class SampleSizeTests(unittest.TestCase):
    def fixture(self, table):
        p=next(r for r in entries() if r['table_id']==table)
        g={**p,'reviewed_source':{'caption':p['source_quote'],'table_sha256':p['table_sha256']},'scores':[]}
        return p,{'score_groups':[g],'benchmarks':[],'observations':[]}
    def test_subset_is_not_dataset_total(self):
        p,s=self.fixture('553569b6d5ec207810ec91c74976');annotate(s)
        self.assertEqual(s['score_groups'][0]['evaluation_n'],48)
        self.assertEqual(s['score_groups'][0]['sample_size']['dataset_total_n'],92)
    def test_repeated_runs_are_not_questions(self):
        _,s=self.fixture('b58de3de1f8f39c45702760f6c67');annotate(s)
        self.assertEqual(s['score_groups'][0]['evaluation_n'],1000)
        self.assertEqual(s['score_groups'][0]['sample_size']['repetitions'],3)
    def test_changed_source_or_metric_not_reused(self):
        _,s=self.fixture('4bf14f383fb5078f7ecd48dd4a26')
        s['score_groups'][0]['reviewed_source']={'caption':'Bootstrap n=2000; 3 runs'}
        annotate(s);self.assertIsNone(s['score_groups'][0]['evaluation_n'])
        _,s=self.fixture('4bf14f383fb5078f7ecd48dd4a26');s['score_groups'][0]['metric']='Other metric'
        annotate(s);self.assertIsNone(s['score_groups'][0]['evaluation_n'])
    def test_absent_count_stays_null(self):
        s={'score_groups':[{'paper_id':'unknown','scores':[{'value_numeric':95}]}]}
        before=deepcopy(s);annotate(s)
        self.assertEqual(before['score_groups'][0]['scores'],s['score_groups'][0]['scores'])
        self.assertIsNone(s['score_groups'][0]['evaluation_n'])
