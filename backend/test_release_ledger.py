import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'runtime'))
from recent_benchmarks.release_ledger import build_ledger, event_day
import build_release_ledger as cli


def proof(url='https://example.org/benchmark/news'):
    return {'primary': True, 'review_status': 'VERIFIED', 'url': url,
            'quote': 'We introduce the benchmark today.', 'reviewed_at': '2026-11-16T00:00:00Z'}


def entity():
    return {'entity_id': 'bench-public-1', 'name': 'ExampleBench', 'kind': 'BENCHMARK',
            'scope': 'LLM', 'decision': 'CONFIRMED_NEW', 'identity_evidence': proof(),
            'firstness_evidence': proof(), 'source_refs': [],
            'events': [{'kind': 'FIRST_PUBLIC_INTRODUCTION', 'at': '2026-11-11T20:00:00Z',
                        'date_basis': 'PUBLISHER_RELEASE_TIMESTAMP',
                        'evidence': proof()}]}


def report(rows=(), entries=()):
    return build_ledger(rows, {'version': 1, 'entities': list(entries)},
        snapshot_id='snapshot-1', source_sha256='f'*64, source_generated_at='2026-11-16T01:00:00Z',
        period_start='2026-11-02', period_end='2026-11-16', as_of='2026-11-16T01:00:00Z')


class ReleaseLedgerTests(unittest.TestCase):
    def test_reviewed_real_cases_do_not_count_components_or_updates(self):
        registry = json.loads((HERE/'release-evidence.json').read_text(encoding='utf-8'))
        rows = [dict(ref, benchmark_name=e['name'], eligibility='ELIGIBLE',
                     date_basis='PAPER_V1_PROXY', release_date='2026-11-14')
                for e in registry['entities'] for ref in e['source_refs']]
        r = report(rows,registry['entities'])
        self.assertEqual(r['daily']['dispositions']['NOT_A_BENCHMARK'],12)
        self.assertEqual(r['daily']['confirmed_minimum_in_period'],4)
        confirmed=[e for e in r['entities'] if e['status']=='CONFIRMED_NEW_FIRST_PUBLIC']
        self.assertEqual(sorted((e['name'],e['first_public_date']) for e in confirmed),
                         [('MVDriveBench','2026-11-13'),('NIBench','2026-11-13'),
                          ('ToolTurns','2026-11-11'),('WordInferBench','2026-11-13')])

    def test_future_release_is_pending(self):
        e = entity()
        e['events'][0]['at'] = '2026-11-17T00:00:00Z'
        r = report(entries=[e])
        self.assertEqual(r['daily']['confirmed_minimum_in_period'], 0)
        self.assertEqual(r['entities'][0]['reasons'], ['EVENT_AFTER_AUDIT_CUTOFF'])

    def test_paper_proxy_and_scores_never_credit_release(self):
        row = {'paper_id': 'p1', 'benchmark_id': 'b1', 'benchmark_name': 'NewBench',
               'novelty': 'NEW', 'eligibility': 'ELIGIBLE', 'date_basis': 'PAPER_V1_PROXY',
               'release_date': '2026-11-14', 'paper_first_published': '2026-11-14',
               'observations': 1000, 'evidence_quote': 'We introduce NewBench.'}
        d = report([row])['daily']
        self.assertEqual(d['confirmed_minimum_in_period'], 0)
        self.assertEqual(d['unallocated_pending_entities'], 1)
        self.assertIsNone(d['daily_average'])
        self.assertTrue(all(x['daily_total'] is None and x['display'] == '待核' for x in d['days']))

    def test_new_release_does_not_require_scores(self):
        d = report(entries=[entity()])['daily']
        self.assertEqual(d['confirmed_minimum_in_period'], 1)
        self.assertEqual(next(x for x in d['days'] if x['date'] == '2026-11-12')['confirmed_minimum'], 1)

    def test_artifact_release_does_not_reset_introduction(self):
        e = entity()
        e['events'][0]['at'] = '2026-10-15T10:00:00Z'
        e['events'].append({'kind': 'DATA_RELEASE', 'at': '2026-11-14T10:00:00Z', 'evidence': proof()})
        self.assertEqual(report(entries=[e])['daily']['confirmed_minimum_in_period'], 0)

    def test_only_code_release_is_not_first_publication(self):
        e = entity(); e['events'][0]['kind'] = 'CODE_RELEASE'
        r = report(entries=[e])
        self.assertEqual(r['entities'][0]['status'], 'PENDING_FIRST_PUBLICATION')
        self.assertEqual(r['daily']['confirmed_minimum_in_period'], 0)

    def test_metrics_splits_ablations_never_count(self):
        entries = []
        for kind in ('METRIC', 'SUBSET', 'ABLATION', 'SUBTASK', 'MIRROR'):
            e = entity(); e.update(entity_id=kind, kind=kind, decision='NOT_A_BENCHMARK'); entries.append(e)
        r = report(entries=entries)
        self.assertEqual(r['daily']['confirmed_minimum_in_period'], 0)
        self.assertFalse(r['review_queue'])

    def test_misclassified_metric_cannot_be_confirmed_new(self):
        e = entity(); e['kind'] = 'METRIC'
        with self.assertRaises(ValueError): report(entries=[e])

    def test_old_or_update_never_counts_as_new(self):
        e = entity(); e['decision'] = 'EXISTING_OR_UPDATE'
        self.assertEqual(report(entries=[e])['daily']['confirmed_minimum_in_period'], 0)

    def test_firstness_review_cannot_be_omitted(self):
        e = entity(); e.pop('firstness_evidence')
        with self.assertRaises(ValueError): report(entries=[e])

    def test_unverified_date_is_pending_not_zero(self):
        e = entity(); e['events'][0] = {'kind': 'FIRST_PUBLIC_INTRODUCTION', 'date': '2026-11-14',
                                      'date_basis': 'AUTHOR_DATED_ANNOUNCEMENT', 'evidence': proof()}
        r = report(entries=[e])
        self.assertEqual(r['entities'][0]['status'], 'PENDING_FIRST_PUBLICATION')
        self.assertIsNone(r['daily']['period_total'])

    def test_date_only_with_known_zone_is_supported(self):
        day, issue = event_day({'date': '2026-11-14', 'timezone': 'Asia/Shanghai'})
        self.assertEqual((day, issue), ('2026-11-14', None))

    def test_conflicting_first_dates_do_not_choose_earliest(self):
        e = entity(); e['events'].append({'kind': 'FIRST_PUBLIC_INTRODUCTION', 'at': '2026-11-13T01:00:00Z',
                                       'date_basis': 'PUBLISHER_RELEASE_TIMESTAMP', 'evidence': proof()})
        r = report(entries=[e])
        self.assertEqual(r['entities'][0]['status'], 'PENDING_CONFLICTING_FIRST_DATES')
        self.assertEqual(r['daily']['confirmed_minimum_in_period'], 0)

    def test_unverified_primary_event_is_pending(self):
        e = entity(); e['events'][0]['evidence']['primary'] = False
        self.assertEqual(report(entries=[e])['daily']['confirmed_minimum_in_period'], 0)

    def test_exact_bindings_count_aliases_once(self):
        e = entity(); e['source_refs'] = [{'paper_id': 'p1', 'benchmark_id': 'a'}, {'paper_id': 'p2', 'benchmark_id': 'b'}]
        rows = [dict(paper_id=p, benchmark_id=b, benchmark_name=n) for p,b,n in [('p1','a','EXB'),('p2','b','ExampleBench')]]
        r = report(rows, [e])
        self.assertEqual(len(r['entities']), 1)
        self.assertEqual(r['daily']['confirmed_minimum_in_period'], 1)

    def test_homonyms_without_binding_are_not_merged(self):
        rows = [dict(paper_id=p, benchmark_id='b', benchmark_name='SameName', date_basis='FIRST_DISCLOSURE') for p in ['p1','p2']]
        self.assertEqual(len(report(rows)['review_queue']), 2)

    def test_duplicate_snapshot_rows_are_idempotent(self):
        row = dict(paper_id='p1', benchmark_id='b1', date_basis='FIRST_DISCLOSURE')
        self.assertEqual(report([row, row])['daily']['source_records'], 1)

    def test_conflicting_source_duplicate_is_rejected(self):
        a = dict(paper_id='p1', benchmark_id='b1', benchmark_name='First')
        with self.assertRaises(ValueError): report([a, dict(a, benchmark_name='Second')])

    def test_one_source_cannot_bind_two_entities(self):
        a = entity(); a['source_refs'] = [{'paper_id': 'p', 'benchmark_id': 'b'}]
        b = copy.deepcopy(a); b['entity_id'] = 'other'
        with self.assertRaises(ValueError): report(entries=[a,b])

    def test_eval_eligibility_does_not_imply_novelty(self):
        row = dict(paper_id='p1', benchmark_id='b1', date_basis='UNKNOWN', eligibility='ELIGIBLE')
        r = report([row])
        self.assertEqual(r['daily']['unclassified_evaluation_records'], 1)
        self.assertEqual(r['daily']['confirmed_minimum_in_period'], 0)

    def test_builder_does_not_mutate_scoring_inputs(self):
        rows = [dict(paper_id='p', benchmark_id='b', date_basis='FIRST_DISCLOSURE', scores=[{'value': 8}])]
        original = copy.deepcopy(rows); e = entity(); original_e = copy.deepcopy(e)
        report(rows, [e]); self.assertEqual(rows, original); self.assertEqual(e, original_e)

    def test_invalid_evidence_url_does_not_credit(self):
        e = entity(); e['events'][0]['evidence']['url'] = 'https://user:password@example.org/'
        self.assertEqual(report(entries=[e])['daily']['confirmed_minimum_in_period'], 0)


@unittest.skipUnless(importlib.util.find_spec('ijson'), 'ijson is needed for streamed CLI checks')
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.p = Path(self.tmp.name)
        raw = gzip.compress(json.dumps({'snapshot_id': 's1', 'benchmarks': []}).encode(), mtime=0)
        (self.p/'source.json.gz').write_bytes(raw)
        self.pub = {'snapshot_id': 's1', 'generated_at': '2026-11-16T01:00:00Z', 'source_sha256': hashlib.sha256(raw).hexdigest()}
        (self.p/'publication.json').write_text(json.dumps(self.pub))
        (self.p/'registry.json').write_text(json.dumps({'version':1,'entities':[entity()]}))

    def tearDown(self): self.tmp.cleanup()

    def build(self):
        return cli.run(self.p/'source.json.gz', self.p/'publication.json', self.p/'registry.json', self.p/'out')

    def test_hash_and_snapshot_checks_preserve_last_good_pointer(self):
        self.build(); before = (self.p/'out/current.json').read_bytes()
        self.pub['source_sha256'] = '0'*64
        (self.p/'publication.json').write_text(json.dumps(self.pub))
        with self.assertRaises(ValueError): self.build()
        self.assertEqual((self.p/'out/current.json').read_bytes(), before)

    def test_snapshot_id_must_match_even_with_correct_hash(self):
        self.pub['snapshot_id'] = 'different'
        (self.p/'publication.json').write_text(json.dumps(self.pub))
        with self.assertRaises(ValueError): self.build()
        self.assertFalse((self.p/'out/current.json').exists())

    def test_publication_is_complete_hash_verified_and_replayable(self):
        m, d = self.build(); m2, d2 = self.build()
        self.assertEqual((m,d), (m2,d2))
        for f in m['files'].values():
            raw = (self.p/'out'/f['path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), f['sha256'])
        self.assertIsNone(d['period_total'])


if __name__ == '__main__': unittest.main()
