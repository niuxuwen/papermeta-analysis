import copy
import unittest
from common_basket import calibrate

PANEL=dict(version='test',sha256='testhash',references=[dict(model='A',weight=.5),dict(model='B',weight=.5)])


class CommonBasketTests(unittest.TestCase):
    def test_origin_invariance_and_preserves_difference(self):
        rows=[dict(model='A',elo=1600),dict(model='B',elo=1200),dict(model='C',elo=1900)]
        shifted=[dict(r,elo=r['elo']+900) for r in rows]
        for board in [rows,shifted]:calibrate(board,panel=PANEL)
        self.assertEqual([r['elo'] for r in rows],[r['elo'] for r in shifted])
        self.assertEqual(rows[0]['elo']-rows[1]['elo'],400)
        self.assertEqual((rows[0]['elo']+rows[1]['elo'])/2,1000)
        self.assertEqual(rows[2]['score'],1500)
        before=copy.deepcopy(rows);calibrate(rows,panel=PANEL)
        self.assertEqual(rows,before)

    def test_missing_reference_fails_before_mutating(self):
        rows=[dict(model='A',elo=1600)];before=copy.deepcopy(rows)
        with self.assertRaisesRegex(ValueError,'missing'):calibrate(rows,panel=PANEL)
        self.assertEqual(rows,before)

    def test_exact_alias_not_model_generation_merge(self):
        p=dict(version='test',references=[dict(model='Claude4.5 Haiku',weight=1)])
        rows=[dict(model='Claude 4.5 Haiku',elo_scale=1200),dict(model='Claude 4.6 Haiku',elo_scale=1400)]
        calibrate(rows,elo_key='elo_scale',panel=p)
        self.assertEqual([r['score'] for r in rows],[1000,1200])

    def test_no_anchor_reselection_from_visible_roster(self):
        rows=[dict(model='A',elo=1600,papers=1),dict(model='B',elo=1200,papers=1),dict(model='C',elo=1900,papers=10)]
        audit=calibrate(rows,panel=PANEL)
        visible=[r for r in rows if r['papers']>=7]
        self.assertEqual(visible[0]['score'],1500)
        self.assertEqual(audit['reference_count'],2)

    def test_reference_paper_minimum_is_inclusive_and_does_not_filter_models(self):
        panel={**PANEL,'selection':dict(minimum_independent_papers_per_board=12)}
        rows=[dict(model='A',elo=1600,papers=12),dict(model='B',elo=1200,papers=13),dict(model='C',elo=1900,papers=1)]
        calibrate(rows,panel=panel)
        self.assertEqual(len(rows),3)
        rows[0]['papers']=11
        before=copy.deepcopy(rows)
        with self.assertRaisesRegex(ValueError,'paper minimum'):calibrate(rows,panel=panel)
        self.assertEqual(rows,before)


if __name__=='__main__':unittest.main()
