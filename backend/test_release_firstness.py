import unittest
from arxiv_firstness import Announcements,introduction,prior_search_clear


class FirstnessTests(unittest.TestCase):
    def test_actual_announcement_day_is_separate_from_submission_day(self):
        p=Announcements();p.feed('<h3>Fri, 13 Nov 2026 (showing 1 of 1 entries)</h3><dl><dt><a href="/abs/2611.15189">arXiv:2611.15189</a></dt></dl>')
        self.assertEqual(p.entries['2611.15189']['date'],'2026-11-13')

    def test_method_or_variant_name_does_not_inherit_benchmark_status(self):
        self.assertIsNone(introduction('We propose FIBER, a model evaluated on a large benchmark. A variant called FIBER-Stream improves accuracy.','FIBER-Stream'))
        self.assertIsNone(introduction('We propose EM-TRACE, a stage-wise framework evaluated on a benchmark.','EM-TRACE'))
        self.assertIsNone(introduction('We introduce BaseBench-Plus, a new benchmark.','BaseBench'))
        self.assertIsNotNone(introduction('We introduce WordInferBench, a benchmark of 280 tasks.','WordInferBench'))

    def test_prior_search_must_include_current_paper_and_no_other_identity(self):
        feed=lambda ids:('<feed xmlns="http://www.w3.org/2005/Atom">'+''.join('<entry><id>http://arxiv.org/abs/'+i+'v1</id></entry>'for i in ids)+'</feed>').encode()
        self.assertEqual(prior_search_clear(feed(['2611.15189']),'2611.15189'),(True,None))
        self.assertFalse(prior_search_clear(feed([]),'2611.15189')[0])
        self.assertFalse(prior_search_clear(feed(['2611.15189','2501.12345']),'2611.15189')[0])


if __name__=='__main__':unittest.main()
