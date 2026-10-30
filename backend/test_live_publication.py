import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.modules.setdefault('fcntl', types.SimpleNamespace())
sys.path.insert(0, str(Path(__file__).parent))
from publish_live import public_source, credential_scan, encode
from build_live import build


class PublicationTests(unittest.TestCase):
    def source(self):
        return {'snapshot_id': 'a'*24, 'generated_at': '2026-10-30T01:00:00Z', 'window': {'days': 60},
            'status': {'counts': {'observations': 1}, 'jobs': [{'pid': 12}], 'model': 'private'},
            'benchmarks': [{'paper_id': 'p', 'benchmark_id': 'b', 'benchmark_name': 'Test',
                'progress': {'observations': 1, 'log_path': '/private/log'}}],
            'observations': [{'paper_id': 'p', 'benchmark_id': 'b', 'model_canonical': 'GPT-5.2', 'value_numeric': 32.5}],
            'index': {'method': {'version': 15}, 'models': [{'model_canonical': 'GPT-5.2', 'score': 64.332318}],
                'groups': [], 'relative_reference_audit': {'settings': [{'latent_fit': 'solver cache'}]}},
            'internal_runtime': {'credentials': 'never publish'}}

    def test_export_preserves_scores_and_excludes_runtime(self):
        source = self.source()
        result = public_source(source)
        self.assertEqual(result['observations'][0]['value_numeric'], 32.5)
        self.assertEqual(result['index']['models'][0]['score'], 64.332318)
        self.assertEqual(result['status']['jobs'], [])
        self.assertNotIn('internal_runtime', result)
        self.assertNotIn('log_path', result['benchmarks'][0]['progress'])
        self.assertNotIn('latent_fit', result['index']['relative_reference_audit']['settings'][0])

    def test_secrets_and_unreviewed_methods_refused(self):
        for raw in [b'{"api_key":"x"}', b'Bearer '+b'x'*40, b'sk-or-v1-'+b'a'*40]:
            with self.assertRaises(ValueError): credential_scan(raw)
        source = self.source();source['index']['method']['version'] = 999
        with self.assertRaises(ValueError):public_source(source)

    def test_build_exact_sources_and_refuse_corrupt_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);feed = root/'feed';feed.mkdir();site = root/'site';(site/'snapshot').mkdir(parents=True)
            source = public_source(self.source());raw = gzip.compress(encode(source),mtime=0)
            rules = gzip.compress(encode({'snapshot_id': source['snapshot_id'], 'groups': {}}),mtime=0)
            report = {'publisher':'radar-publication-v1','snapshot_id':source['snapshot_id'], 'observations':1,
                'source_sha256':hashlib.sha256(raw).hexdigest(),'source_bytes':len(raw),
                'rules_sha256':hashlib.sha256(rules).hexdigest(),'rules_bytes':len(rules)}
            for name,data in [('source.json.gz',raw),('task-measurements.json.gz',rules),('publication.json',encode(report))]:
                (feed/name).write_bytes(data)
            build(feed,site,root/'rules.json')
            manifest=json.loads((site/'snapshot/manifest.json').read_text())
            detail=json.loads(gzip.decompress((site/next(iter(manifest['details'].values()))).read_bytes()))
            self.assertEqual(detail['observations'],source['observations'])
            self.assertEqual(detail['benchmark'],source['benchmarks'][0])
            (feed/'source.json.gz').write_bytes(b'broken')
            with self.assertRaises(AssertionError):build(feed,site,root/'rules.json')


if __name__ == '__main__':unittest.main()
