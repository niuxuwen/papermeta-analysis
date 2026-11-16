import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urljoin

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from recent_benchmarks.benchmark_dates import date_assessment
from recent_benchmarks.release_judgment import answer, bucket, judgment, normalize_query, query_index
from build_release_api import artifacts
from query_release_api import query_api
from test_release_ledger import entity, proof, report


class JudgmentTests(unittest.TestCase):
    def test_unknown_is_pending_not_existing(self):
        r=answer('UnknownBench',{},{});self.assertIsNone(r['is_new_in_report_period'])
        self.assertEqual(r['judgment'],'PENDING');self.assertTrue(r['needs_research'])

    def test_homonyms_require_selection(self):
        records=report([dict(paper_id=p,benchmark_id=p,benchmark_name='SameBench',date_basis='PAPER_V1_PROXY') for p in ['p1','p2']])['query_records']
        index=query_index(records);values={r['entity_id']:judgment(r,{'start':'2026-11-02','end_exclusive':'2026-11-16'})for r in records}
        a=answer('SameBench',values,index);self.assertEqual(a['result_status'],'AMBIGUOUS')
        self.assertIsNone(a['is_new_in_report_period'])
        self.assertEqual(answer('SameBench',values,index,paper_id='p1')['match_count'],1)

    def test_all_source_rows_get_overlay_without_changing_proxy(self):
        row=dict(paper_id='p',benchmark_id='b',benchmark_name='Old',release_date='2026-11-14',date_basis='PAPER_V1_PROXY')
        before=copy.deepcopy(row);r=report([row]);self.assertEqual(row,before)
        d=r['date_overlay'][0];self.assertEqual(d['release_date'],'2026-11-14')
        self.assertIsNone(d['benchmark_first_public_date']);self.assertEqual(d['benchmark_date_status'],'PENDING')

    def test_unclassified_evaluation_is_queryable_and_date_unknown(self):
        r=report([dict(paper_id='p',benchmark_id='b',benchmark_name='UnknownOld',date_basis='UNKNOWN')])
        self.assertEqual(r['daily']['unclassified_evaluation_records'],1)
        self.assertEqual(len(r['query_records']),1);self.assertEqual(len(r['date_overlay']),1)

    def test_commit_date_is_not_code_release_or_first_public_date(self):
        r={'events':[dict(kind='CODE_RELEASE',at='2026-11-10T01:00:00Z',beijing_date='2026-11-10',evidence_verified=True,date_issue=None,publication_verified=False)]}
        d=date_assessment(r);self.assertEqual(d['code_release_dates'],[])
        self.assertIsNone(d['first_public_on_or_before']);self.assertIsNone(d['benchmark_first_public_date'])

    def test_future_artifact_is_not_already_released(self):
        e=entity();e['decision']='PENDING';e['events']=[dict(kind='DATA_RELEASE',at='2026-11-20T00:00:00Z',evidence=proof(),publication_verified=True,proves_public_existence=True)]
        d=date_assessment(report(entries=[e])['entities'][0])
        self.assertEqual(d['data_release_dates'],[]);self.assertIsNone(d['first_public_on_or_before'])

    def test_public_existence_only_establishes_upper_bound(self):
        e=entity();e['decision']='PENDING';e['events']=[dict(kind='KNOWN_PUBLIC_EXISTENCE',at='2026-11-06T06:57:16Z',evidence=proof(),publication_verified=True,proves_public_existence=True)]
        r=report(entries=[e])['entities'][0];d=date_assessment(r)
        self.assertIsNone(d['benchmark_first_public_date']);self.assertEqual(d['first_public_on_or_before'],'2026-11-06')

    def test_date_only_author_launch_is_not_exact_beijing_day(self):
        e=entity();e['decision']='PENDING';e['events']=[dict(kind='PUBLIC_ANNOUNCEMENT',date='2026-11-11',author_date_claim='2026-11-11',timezone='UNSPECIFIED',evidence=proof(),publication_verified=True,proves_public_existence=True)]
        d=date_assessment(report(entries=[e])['entities'][0])
        self.assertIsNone(d['benchmark_first_public_date']);self.assertEqual(d['first_public_on_or_before'],'2026-11-12')
        self.assertEqual(d['author_date_claims'][0]['author_date_claim'],'2026-11-11')

    def test_earlier_public_evidence_blocks_later_first_date(self):
        e=entity();e['events'].append(dict(kind='KNOWN_PUBLIC_EXISTENCE',at='2026-11-03T00:00:00Z',evidence=proof(),proves_public_existence=True,publication_verified=True))
        r=report(entries=[e]);self.assertEqual(r['daily']['confirmed_minimum_in_period'],0)
        self.assertIn('FIRST_INTRODUCTION_AFTER_KNOWN_PUBLIC_EVIDENCE',r['entities'][0]['reasons'])

    def test_old_verified_first_date_is_kept_independently_of_update_decision(self):
        e=entity();e['decision']='EXISTING_OR_UPDATE';e['events'][0]['at']='2026-11-01T07:28:49Z'
        r=report(entries=[e]);d=date_assessment(r['entities'][0])
        self.assertEqual(d['benchmark_first_public_date'],'2026-11-01')
        self.assertEqual(r['daily']['confirmed_minimum_in_period'],0)

    def test_arxiv_urls_and_unicode_normalize_without_fuzzy_name_merging(self):
        self.assertEqual(normalize_query(' https://arxiv.org/html/2611.14925v2 '),'2611.14925')
        self.assertEqual(normalize_query('ＴｏｏｌＴｕｒｎｓ'),'toolturns')
        self.assertNotEqual(normalize_query('MMLU-Pro'),normalize_query('MMLU'))
        with self.assertRaises(ValueError):normalize_query('x'*513)

    def fixture(self):
        result=report(entries=[entity()]);meta={'snapshot_id':'s','source_sha256':'a'*64,
            'source_generated_at':'2026-11-16T00:00:00Z','registry_sha256':'b'*64,
            'generation':'c'*24,'report_period':result['daily']['period']}
        files=artifacts(result,meta);root='https://example.org/releases/g/api/v1/'
        mapping={root+k.removeprefix('api/v1/'):v for k,v in files.items() if k.startswith('api/v1/')}
        return files,root,mapping

    def test_real_http_query_client_uses_hash_checked_shards(self):
        _,root,mapping=self.fixture();r=query_api('ExampleBench',root+'manifest.json',fetch=mapping.__getitem__)
        self.assertEqual(r['match_count'],1);self.assertTrue(r['is_new_in_report_period'])
        self.assertEqual(r['matches'][0]['benchmark_first_public_date'],'2026-11-12')

    def test_client_corruption_fails_not_false_existing(self):
        _,root,mapping=self.fixture();url=root+'lookup/'+bucket('examplebench')+'.json';mapping[url]=b'corrupt'
        with self.assertRaisesRegex(ValueError,'integrity'):query_api('ExampleBench',root+'manifest.json',fetch=mapping.__getitem__)

    def test_empty_bucket_returns_pending_without_requesting_missing_file(self):
        _,root,mapping=self.fixture();r=query_api('unseen',root+'manifest.json',fetch=mapping.__getitem__)
        self.assertEqual(r['result_status'],'NOT_FOUND');self.assertIsNone(r['is_new_in_report_period'])

    def test_changed_snapshot_in_validly_hashed_shard_is_rejected(self):
        import hashlib
        _,root,mapping=self.fixture();p='lookup/'+bucket('examplebench')+'.json';data=json.loads(mapping[root+p]);data['snapshot_id']='other';raw=json.dumps(data).encode();mapping[root+p]=raw
        m=json.loads(mapping[root+'manifest.json']);m['lookup'][bucket('examplebench')].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());mapping[root+'manifest.json']=json.dumps(m).encode()
        with self.assertRaisesRegex(ValueError,'snapshot'):query_api('ExampleBench',root+'manifest.json',fetch=mapping.__getitem__)


if __name__=='__main__':unittest.main()
