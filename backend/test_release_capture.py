import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform=='linux','production flock behavior requires Linux')
class CaptureTests(unittest.TestCase):
    def fixture(self,root):
        feed=root/'deployment/publication/feed/feed';feed.mkdir(parents=True)
        raw=b'pinned-source';(feed/'source.json.gz').write_bytes(raw)
        publication={'publisher':'radar-publication-v1','snapshot_id':'s',
                     'source_sha256':hashlib.sha256(raw).hexdigest()}
        (feed/'publication.json').write_text(json.dumps(publication))
        return feed,publication

    def test_busy_score_publisher_does_not_starve_consistent_read(self):
        from automatic_date_service import capture,locked
        with tempfile.TemporaryDirectory()as t:
            root=Path(t);feed,pub=self.fixture(root)
            with locked(root/'deployment/publication/publisher.lock')as acquired:
                self.assertTrue(acquired)
                self.assertEqual(capture(root,root/'dates'),pub)
            self.assertEqual((root/'dates/input/source.json.gz').read_bytes(),b'pinned-source')

    def test_concurrent_manifest_change_rejects_torn_capture(self):
        import automatic_date_service as service
        with tempfile.TemporaryDirectory()as t:
            root=Path(t);feed,pub=self.fixture(root);original=service.shutil.copyfile
            def torn(src,dst):
                original(src,dst);changed={**pub,'source_sha256':'0'*64}
                (feed/'publication.json').write_text(json.dumps(changed))
            with patch.object(service.shutil,'copyfile',side_effect=torn),patch('time.sleep'):
                self.assertIsNone(service.capture(root,root/'dates'))
            self.assertFalse((root/'dates/input/source.json.gz').exists())


if __name__=='__main__':unittest.main()
