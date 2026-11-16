import copy
import unittest

from recent_benchmarks.release_ledger import build_ledger
from recent_benchmarks.benchmark_date_table import build_table


def result(rows, entities=()):
    return build_ledger(rows, {'version':1, 'entities':list(entities)}, snapshot_id='s', source_sha256='h',
        source_generated_at='2026-11-17T01:00:00Z', as_of='2026-11-17T01:00:00Z',
        period_start='2026-11-03', period_end='2026-11-17')


def row(p, name='ExampleBench', day='2026-11-12T18:00:00Z', **kw):
    return dict(paper_id=p, benchmark_id='b', benchmark_name=name,
        paper_first_published=day, date_basis='PAPER_V1_PROXY', **kw)


class DateRegisterTests(unittest.TestCase):
    def test_fallback_deduplicates_names_and_uses_earliest_paper_in_beijing(self):
        source=[row('p1'), row('p2', name='ＥｘａｍｐｌｅＢｅｎｃｈ', day='2026-11-10T18:00:00Z')]
        before=copy.deepcopy(source);r=result(source);t=build_table(r)
        self.assertEqual(len(t['entries']),1);e=t['entries'][0]
        self.assertEqual(e['benchmark_date'],'2026-11-11');self.assertTrue(e['date_is_fallback'])
        self.assertEqual(len(e['source_refs']),2);self.assertEqual(source,before)
        self.assertEqual(r['daily']['confirmed_minimum_in_period'],0)
        self.assertEqual(r['daily']['date_register']['period_new_benchmark_claims'],1)

    def test_existing_table_is_reused_when_old_paper_leaves_window(self):
        t=build_table(result([row('p1',day='2026-10-01T00:00:00Z')]))
        t2=build_table(result([row('p2')]),t)
        self.assertEqual(t2['entries'][0]['benchmark_date'],'2026-10-01')
        self.assertEqual(t2['entries'][0]['revision'],1)
        self.assertEqual(t2['summary']['period_new_benchmark_claims'],0)

    def test_earlier_paper_updates_register_with_history(self):
        t=build_table(result([row('p1')]))
        r=result([row('p2',day='2026-11-05T00:00:00Z')]);t2=build_table(r,t)
        self.assertEqual(t2['entries'][0]['benchmark_date'],'2026-11-05')
        self.assertEqual(t2['entries'][0]['revision'],2)
        self.assertEqual(len(t2['entries'][0]['changes']),2)

    def test_stronger_public_evidence_can_correct_submission_proxy_later(self):
        r=result([row('p1')]);t=build_table(r)
        r=result([row('p1')]);record=r['query_records'][0]
        record['events']=[{'kind':'KNOWN_PUBLIC_EXISTENCE','beijing_date':'2026-11-16',
            'evidence_verified':True,'publication_verified':True,'proves_public_existence':True}]
        t2=build_table(r,t);self.assertEqual(t2['entries'][0]['benchmark_date'],'2026-11-16')
        self.assertEqual(t2['entries'][0]['date_basis'],'PRIMARY_PUBLIC_DATE')
        self.assertFalse(t2['entries'][0]['date_is_fallback'])

    def test_earlier_primary_proof_invalidates_cached_later_first_date(self):
        r=result([row('p1')]);t=build_table(r);t['entries'][0].update(benchmark_date='2026-11-13',date_basis='VERIFIED_FIRST_PUBLIC',date_is_fallback=False)
        r=result([row('p1')]);r['query_records'][0]['events']=[{'kind':'KNOWN_PUBLIC_EXISTENCE','beijing_date':'2026-11-05','evidence_verified':True,'publication_verified':True,'proves_public_existence':True}]
        e=build_table(r,t)['entries'][0]
        self.assertEqual(e['benchmark_date'],'2026-11-05');self.assertEqual(e['date_basis'],'PRIMARY_PUBLIC_DATE')

    def test_exclusion_is_retained_and_is_not_resurrected_by_new_paper(self):
        r=result([row('p1')]);r['query_records'][0].update(status='NOT_A_BENCHMARK',kind='METHOD')
        t=build_table(r);t2=build_table(result([row('p2')]),t)
        self.assertTrue(t2['entries'][0]['excluded']);self.assertIsNone(t2['entries'][0]['benchmark_date'])
        self.assertEqual(t2['summary']['period_new_benchmark_claims'],0)

    def test_all_records_get_table_entries_but_unknown_is_not_new_claim(self):
        a=row('p1');a['date_basis']='UNKNOWN';r=result([a]);t=build_table(r)
        self.assertEqual(t['summary']['dated_benchmarks'],1)
        self.assertEqual(t['summary']['period_new_benchmark_claims'],0)

    def test_source_quote_matches_do_not_split_one_name_into_per_paper_entities(self):
        r=result([row('p1'),row('p2')])
        for i,record in enumerate(r['query_records']):record.update(entity_id='auto-source-'+str(i),identity_evidence={'quote':'verified mention'})
        t=build_table(r);self.assertEqual(len(t['entries']),1);self.assertEqual(len(t['entries'][0]['source_refs']),2)
        old=copy.deepcopy(t);e=old['entries'][0];old['entries']=[{**e,'benchmark_key':'entity:auto-source-0'},{**e,'benchmark_key':'entity:auto-source-1'}]
        t2=build_table(r,old);self.assertEqual(len(t2['entries']),1)

    def test_later_reuse_does_not_erase_the_original_new_claim(self):
        t=build_table(result([row('p1'),row('p2',novelty='EXISTING')]))
        self.assertEqual(t['entries'][0]['newness'],'SOURCE_NEW_CLAIM')

    def test_no_paper_date_does_not_borrow_ingestion_time(self):
        t=build_table(result([row('p1',day=None),row('p2',name='Future',day='2027-01-01')]))
        self.assertEqual(t['summary']['missing_dates'],2)

    def test_distinct_versions_remain_separate(self):
        t=build_table(result([row('p1',name='ExampleBench'),row('p2',name='ExampleBench-Pro')]))
        self.assertEqual(len(t['entries']),2)

    def test_replay_is_idempotent_and_keeps_inactive_history(self):
        r=result([row('p1')]);t=build_table(r)
        self.assertEqual(t,build_table(result([row('p1')]),t))
        t2=build_table(result([]),t);self.assertFalse(t2['entries'][0]['active'])


if __name__=='__main__':unittest.main()
