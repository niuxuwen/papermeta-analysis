import gzip
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import publication_transport as transport


class PublicationTransportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.source = self.folder / transport.SOURCE_NAME
        self.packed = gzip.compress(bytes(range(256)) * 64, mtime=0)
        self.source.write_bytes(self.packed)
        self.report = {"source_bytes": len(self.packed),
                       "source_sha256": hashlib.sha256(self.packed).hexdigest()}

    def split(self):
        with patch.multiple(transport, GIT_FILE_LIMIT=150, PART_BYTES=128, BLOCK_BYTES=64):
            return transport.stage_source(self.folder, self.report)

    def assemble(self, target):
        with patch.multiple(transport, PART_BYTES=128, BLOCK_BYTES=64):
            transport.assemble_source(
                self.report, lambda name: (self.folder / name).open("rb"), target)

    def test_legacy_feed_keeps_original_file(self):
        self.assertEqual(transport.stage_source(self.folder, self.report), [self.source.name])
        self.assertNotIn("source_parts", self.report)

    def test_parts_reconstruct_the_original_gzip(self):
        names = self.split()
        self.assertGreater(len(names), 1)
        self.assertEqual(sum((self.folder / name).stat().st_size for name in names), len(self.packed))
        self.source.unlink()
        self.assemble(self.source)
        self.assertEqual(self.source.read_bytes(), self.packed)

    def test_bad_part_preserves_previous_generation(self):
        names = self.split()
        (self.folder / names[0]).write_bytes(b"x" * 128)
        with self.assertRaisesRegex(ValueError, "integrity failure"):
            self.assemble(self.source)
        self.assertEqual(self.source.read_bytes(), self.packed)

    def test_invalid_order_is_rejected_before_reading(self):
        self.split()
        self.report["source_parts"].reverse()
        with self.assertRaisesRegex(ValueError, "Invalid Radar source part"):
            transport.assemble_source(self.report, lambda name: io.BytesIO(), self.source)
