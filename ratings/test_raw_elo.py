import unittest
from raw_elo import annotate, validate

class RawEloTests(unittest.TestCase):
    def test_no_range_clamping_or_reference_requirement(self):
        rows=[dict(elo=x,papers=1) for x in [-100,1000,1742.6,2200]]
        annotate(rows);validate(rows)
        self.assertEqual([r['score'] for r in rows],[-100,1000,1742.6,2200])
    def test_rejects_normalized_display(self):
        with self.assertRaises(ValueError):
            validate([dict(elo=1742.6,score=74.2,score_unit='elo')])
    def test_main_alias(self):
        rows=[dict(elo_scale=1316.)]
        annotate(rows,'elo_scale');validate(rows,'elo_scale')
        self.assertEqual(rows[0]['score'],1316.)
