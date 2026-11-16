import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from build_release_site import build


@unittest.skipUnless(importlib.util.find_spec('ijson'), 'streaming dependency required')
class ReleaseSiteTests(unittest.TestCase):
    def fixture(self, root):
        feed, site = root/'feed', root/'site'
        feed.mkdir(); (site/'snapshot').mkdir(parents=True); (site/'zh').mkdir()
        raw = gzip.compress(json.dumps({'snapshot_id':'snapshot-1','benchmarks':[]}).encode(),mtime=0)
        (feed/'source.json.gz').write_bytes(raw)
        meta = {'snapshot_id':'snapshot-1','source_sha256':hashlib.sha256(raw).hexdigest(),
                'generated_at':'2026-11-16T01:00:00Z'}
        (feed/'publication.json').write_text(json.dumps(meta),encoding='utf-8')
        (site/'snapshot/current.json').write_text(json.dumps(meta),encoding='utf-8')
        for p in [site/'index.html',site/'zh/index.html']:
            p.write_text('<html><main>Existing score content</main></html>',encoding='utf-8')
        registry=root/'registry.json'
        registry.write_text('{"version":1,"entities":[]}',encoding='utf-8')
        return feed,site,registry

    def test_generation_is_coherent_and_links_are_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            feed,site,registry=self.fixture(Path(d))
            first,daily=build(feed,site,registry)
            again,_=build(feed,site,registry)
            self.assertEqual(first,again)
            self.assertIsNone(daily['daily_average'])
            self.assertIn(first['generation']+'/index.html',(site/'releases/index.html').read_text(encoding='utf-8'))
            for p,href in [(site/'index.html','./releases/'),(site/'zh/index.html','../releases/')]:
                text=p.read_text(encoding='utf-8')
                self.assertEqual(text.count('id="benchmark-release-link"'),1)
                self.assertIn(href,text)
                self.assertIn('Existing score content',text)

    def test_score_snapshot_mismatch_refuses_publish(self):
        with tempfile.TemporaryDirectory() as d:
            feed,site,registry=self.fixture(Path(d))
            build(feed,site,registry)
            previous=(site/'releases/current.json').read_bytes()
            (site/'snapshot/current.json').write_text('{"snapshot_id":"different"}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'match the public score snapshot'):
                build(feed,site,registry)
            self.assertEqual(previous,(site/'releases/current.json').read_bytes())


if __name__=='__main__':unittest.main()
