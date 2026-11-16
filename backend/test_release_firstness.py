import unittest
from arxiv_firstness import Announcements,introduction,prior_search_clear,merge_events,search_prior,independent_clearance


class FirstnessTests(unittest.TestCase):
    def test_prior_arxiv_search_alone_cannot_clear_global_firstness(self):
        self.assertFalse(independent_clearance({'review_status':'VERIFIED','source_sha256':'s'},'s'))
        c={'review_status':'VERIFIED','source_sha256':'s','primary_projects_and_prior_publications_reconciled':True,'earliest_source':'THIS_ARXIV_V1','primary_evidence':{'primary':True,'review_status':'VERIFIED','url':'https://example.org/first-introduction','quote':'independently reviewed earliest public introduction','reviewed_at':'2026-11-16T00:00:00Z'}}
        self.assertTrue(independent_clearance(c,'s'));self.assertFalse(independent_clearance(c,'changed'))
    def test_broken_export_api_uses_primary_search_page_and_records_actual_source(self):
        class Cache:
            def get(self,url):
                if 'export.arxiv.org'in url:raise RuntimeError('PRIMARY_HTTP_502')
                from urllib.parse import parse_qs,urlparse
                assert parse_qs(urlparse(url).query)['order']==['-announced_date_first']
                return b'<p class="list-title"><a href="https://arxiv.org/abs/2611.15189">arXiv:2611.15189</a></p>'
        clear,reason,raw,url=search_prior(Cache(),'WordInferBench','2611.15189')
        self.assertTrue(clear);self.assertIsNone(reason);self.assertTrue(url.startswith('https://arxiv.org/search/'))
    def test_repository_research_preserves_paper_date_without_duplicate_events(self):
        e={'kind':'KNOWN_PUBLIC_EXISTENCE','date':'2026-11-13','evidence':{'url':'https://arxiv.org/list/cs.AI/pastweek','quote':'dated entry','reviewed_at':'one'}}
        newer={**e,'evidence':{**e['evidence'],'reviewed_at':'two'}}
        self.assertEqual(merge_events([newer],[e]),[newer])
    def test_actual_announcement_day_is_separate_from_submission_day(self):
        p=Announcements();p.feed('<h3>Fri, 13 Nov 2026 (showing 1 of 1 entries)</h3><dl><dt><a href="/abs/2611.15189">arXiv:2611.15189</a></dt></dl>')
        self.assertEqual(p.entries['2611.15189']['date'],'2026-11-13')
        p.feed('<dd>Earlier related paper: <a href="/abs/2501.12345">citation</a></dd>')
        self.assertNotIn('2501.12345',p.entries)

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
