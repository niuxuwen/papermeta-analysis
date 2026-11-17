import unittest
from recent_benchmarks.benchmark_date_table import paper_counts

PERIOD={'start':'2026-11-03','end_exclusive':'2026-11-17'}
def entry(day, paper='2611.1v1', basis='PAPER_V1_PROXY', **updates):
    return dict(active=True,excluded=False,newness='SOURCE_NEW_CLAIM',identity_basis='NORMALIZED_NAME_ASSUMPTION',
        benchmark_date=day,date_is_fallback=True,source_refs=[{'arxiv_id':paper,'paper_id':paper,'date_basis':basis}],**updates)

class PaperCountTests(unittest.TestCase):
    def test_multiple_benchmarks_versions_and_days_count_one_paper(self):
        r=paper_counts([entry('2026-11-04'),entry('2026-11-05','2611.1v2')],PERIOD)
        self.assertEqual(r['new_benchmark_papers'],1)
        self.assertEqual(next(x for x in r['days']if x['date']=='2026-11-04')['new_benchmark_papers'],1)
        self.assertEqual(sum(x['new_benchmark_papers']for x in r['days']),1)
    def test_earlier_date_outside_window_does_not_remove_in_window_contribution(self):
        r=paper_counts([entry('2026-10-01'),entry('2026-11-06')],PERIOD)
        self.assertEqual(r['new_benchmark_papers'],1)
    def test_reusing_paper_does_not_inherit_benchmark_newness(self):
        r=paper_counts([entry('2026-11-05',basis='UNKNOWN')],PERIOD)
        self.assertEqual(r['new_benchmark_papers'],0)
        self.assertEqual(r['associated_papers'],1)
    def test_existing_excluded_ambiguous_and_inactive_are_omitted(self):
        for field,value in [('excluded',True),('active',False),('newness','EXISTING_OR_UPDATE'),('identity_basis','AMBIGUOUS_REVIEWED_NAME')]:
            e=entry('2026-11-05');e[field]=value
            self.assertEqual(paper_counts([e],PERIOD)['new_benchmark_papers'],0)
    def test_explicit_new_novelty_does_not_require_proxy_date(self):
        e=entry('2026-11-05',basis='DATE_REGISTER');e['source_refs'][0]['novelty']='NEW'
        self.assertEqual(paper_counts([e],PERIOD)['new_benchmark_papers'],1)
    def test_missing_dates_are_visible_and_not_new_count(self):
        r=paper_counts([entry(None)],PERIOD)
        self.assertEqual(r['papers_with_missing_benchmark_dates'],1)
        self.assertEqual(r['new_benchmark_papers'],0)

if __name__=='__main__':unittest.main()
