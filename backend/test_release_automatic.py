import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import automatic_date_review as worker
from recent_benchmarks.automatic_date_policy import catalog,fact_evidence,valid_fact_evidence
from recent_benchmarks.automatic_date_merge import merge_registries
from recent_benchmarks.release_ledger import validate_registry,digest
from test_release_ledger import entity


class AutomaticEvidenceTests(unittest.TestCase):
    def test_api_rate_limit_uses_official_atom_without_exact_first_credit(self):
        class Cache:
            def get(self,url):
                if 'api.github.com'in url:raise RuntimeError('PRIMARY_HTTP_403')
                return b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><updated>2026-11-11T10:00:00Z</updated><link href="https://github.com/owner/project/releases/tag/v1"/><content>First public release of ExampleBench</content></entry></feed>'
        records=worker.release_records('owner/project',Cache())
        self.assertEqual(len(records),1);self.assertTrue(records[0]['_atom_only'])
        self.assertEqual(records[0]['updated_at'],'2026-11-11T10:00:00Z')

    def test_historical_receipt_is_bound_only_and_tamper_protected(self):
        fact=catalog()[0]['facts'][0];p=fact_evidence(fact)
        self.assertTrue(valid_fact_evidence(p))
        altered=copy.deepcopy(p);altered['fact_receipt']['fact']['public_by']='2026-11-14'
        self.assertFalse(valid_fact_evidence(altered))
        e=entity();e['firstness_evidence']=p
        with self.assertRaisesRegex(ValueError,'cannot prove'):validate_registry({'version':1,'entities':[e]})
        e=entity();e['events']=[{'kind':'FIRST_PUBLIC_INTRODUCTION','date':fact['public_by'],'evidence':p}]
        with self.assertRaisesRegex(ValueError,'restricted'):validate_registry({'version':1,'entities':[e]})

    def context(self,aliases=None):
        fact=catalog()[0]['facts'][0];name=fact['name'];q='This paper evaluates '+name+' with the same evaluation setting.'
        b={'benchmark_id':'b','name':name,'aliases':aliases or [],'novelty':'EXISTING','tests_llms':True,'evidence_quote':q}
        context={'raw':{'paper':{'url':'https://arxiv.org/abs/2601.12345v2'},'benchmarks':[b]},
                 'normalized_text':worker.norm(q),'source_sha256':'a'*64}
        row={'paper_id':'p','benchmark_id':'b','benchmark_name':name}
        return row,b,context

    def test_unknown_variant_does_not_inherit_historical_bound(self):
        row,b,c=self.context();selected,error=worker.select_benchmark(row,c);self.assertIsNone(error)
        self.assertIsNotNone(worker.audited_old(row,selected,c))
        b['aliases']=['biased-hint version of '+b['name']]
        selected,_=worker.select_benchmark(row,c);self.assertIsNone(worker.audited_old(row,selected,c))
        b['aliases']=[];b['novelty']='NEW';selected,_=worker.select_benchmark(row,c)
        self.assertIsNone(worker.audited_old(row,selected,c))

    def test_quote_membership_required_and_source_version_preserved(self):
        row,b,c=self.context();selected,_=worker.select_benchmark(row,c)
        record=worker.base_record(row,selected,c)
        self.assertTrue(record['identity_evidence']['url'].endswith('v2'))
        c['normalized_text']='different source'
        self.assertEqual(worker.select_benchmark(row,c)[1],'BENCHMARK_QUOTE_NOT_IN_PINNED_SOURCE')

    def test_stale_auto_ref_cannot_overwrite_manual_or_changed_source(self):
        e=entity();e['source_refs']=[{'paper_id':'p','benchmark_id':'b','source_signature':'s'}]
        env={'format':'automatic-date-registry-v1','registry':{'version':1,'entities':[e]}}
        merged,audit=merge_registries({'version':1,'entities':[]},env,{('p','b'):'changed'})
        self.assertEqual(merged['entities'],[]);self.assertEqual(audit['stale_or_protected_source_updates'],1)
        manual=copy.deepcopy(e);manual['entity_id']='manual'
        merged,audit=merge_registries({'version':1,'entities':[manual]},env,{('p','b'):'s'})
        self.assertEqual(merged['entities'],[manual])

    def test_edited_official_release_proves_updated_bound_only(self):
        row,b,c=self.context();b['checked_quote']=b['evidence_quote']+' https://github.com/owner/project';b['novelty']='NEW'
        c['text']=b['checked_quote']
        name=row['benchmark_name']
        class Cache:
            def get(self,url):
                if '/releases?'in url:return json.dumps([{'published_at':'2026-11-10T10:00:00Z',
                    'updated_at':'2026-11-12T10:00:00Z','tag_name':'v1','body':'First public release of '+name,
                    'html_url':'https://github.com/owner/project/releases/tag/v1'}]).encode()
                return name.encode()
        record,status,_=worker.official_events(row,b,c,Cache())
        self.assertEqual(status,'VERIFIED_PUBLIC_BOUND');self.assertEqual(record['decision'],'PENDING')
        self.assertEqual(record['events'][0]['kind'],'KNOWN_PUBLIC_EXISTENCE')
        self.assertEqual(record['events'][0]['at'],'2026-11-12T10:00:00Z')


@unittest.skipUnless(importlib.util.find_spec('ijson'),'streaming dependency required')
class AutomaticQueueTests(unittest.TestCase):
    def test_local_work_db_checkpoint_survives_process_replacement(self):
        with tempfile.TemporaryDirectory()as t:
            p=Path(t);(p/'data/runs').mkdir(parents=True)
            r=worker.Reviewer(p,p/'state',{'version':1,'entities':[]},p/'scratch.sqlite')
            r.db.execute('INSERT INTO meta VALUES(?,?)',('receipt','saved'));r.persist();r.db.close()
            resumed=worker.Reviewer(p,p/'state',{'version':1,'entities':[]},p/'scratch2.sqlite')
            self.assertEqual(resumed.db.execute('SELECT value FROM meta WHERE key=?',('receipt',)).fetchone()[0],'saved')
            resumed.db.close()

    def test_checkpoint_resume_and_targeted_source_change(self):
        with tempfile.TemporaryDirectory()as t:
            p=Path(t);(p/'data/runs').mkdir(parents=True)
            rows=[{'paper_id':'p'+str(i),'benchmark_id':'b','benchmark_name':'TestBench'}for i in range(2)]
            raw=gzip.compress(json.dumps({'snapshot_id':'s','benchmarks':rows}).encode())
            source=p/'source.gz';source.write_bytes(raw)
            pub={'snapshot_id':'s','source_sha256':hashlib.sha256(raw).hexdigest(),'generated_at':'2026-11-16T01:00:00Z'}
            r=worker.Reviewer(p,p/'state',{'version':1,'entities':[]});r.ingest(source,pub)
            r.sources.stamp=lambda key:[key,'unchanged']
            r.ingest(source,pub)
            r.check=lambda task:('NEEDS_PRIMARY_DATE','PRIMARY_MISSING',None,1)
            progress=r.run(workers=2)
            self.assertTrue(progress['source_pass_complete']);self.assertFalse(progress['all_first_dates_resolved'])
            r.ingest(source,pub);self.assertEqual(r.db.execute("SELECT COUNT(*)FROM tasks WHERE status='PENDING'").fetchone()[0],0)
            r.sources.stamp=lambda key:[key,'changed'if key=='p1'else'unchanged']
            r.ingest(source,pub)
            self.assertEqual(r.db.execute("SELECT COUNT(*)FROM tasks WHERE status='PENDING'").fetchone()[0],1)
            r.db.close()

    def test_gzip_automatic_registry_updates_date_overlay_and_generation(self):
        import build_release_ledger as cli
        with tempfile.TemporaryDirectory()as t:
            p=Path(t);row={'paper_id':'p','benchmark_id':'b','benchmark_name':'ExampleBench'}
            raw=gzip.compress(json.dumps({'snapshot_id':'s','benchmarks':[row]}).encode());(p/'source.gz').write_bytes(raw)
            (p/'publication.json').write_text(json.dumps({'snapshot_id':'s','source_sha256':hashlib.sha256(raw).hexdigest(),'generated_at':'2026-11-16T01:00:00Z'}))
            (p/'manual.json').write_text('{"version":1,"entities":[]}')
            e=entity();e['source_refs']=[{'paper_id':'p','benchmark_id':'b','source_signature':worker.source_signature(row)}]
            env={'format':'automatic-date-registry-v1','registry':{'version':1,'entities':[e]},'progress':{'source_records':1}}
            auto=p/'auto.gz';auto.write_bytes(gzip.compress(json.dumps(env).encode()))
            a,d=cli.run(p/'source.gz',p/'publication.json',p/'manual.json',p/'out',automatic_path=auto)
            self.assertEqual(d['confirmed_minimum_in_period'],1)
            self.assertIn('automatic-review-progress.json',a['files'])
            env['progress']['source_records']=2;auto.write_bytes(gzip.compress(json.dumps(env).encode()))
            b,_=cli.run(p/'source.gz',p/'publication.json',p/'manual.json',p/'out',automatic_path=auto)
            self.assertNotEqual(a['generation'],b['generation'])


if __name__=='__main__':unittest.main()
