import math
import unittest
from copy import deepcopy
from normalization import normalize, validate, reference_panel

class NormalizationTests(unittest.TestCase):
    def panel(self):
        return dict(version='test',references=[dict(model='A',weight=.5),dict(model='B',weight=.5)])
    def rows(self):
        return [dict(model='A',setting='',elo=1200,papers=12),dict(model='B',setting='',elo=1000,papers=20),dict(model='C',setting='',elo=1400,papers=7)]
    def test_rank_and_fit_unchanged(self):
        rows=self.rows();original=deepcopy(rows)
        audit=normalize(rows,panel=self.panel());validate(rows,audit)
        self.assertEqual([{k:v for k,v in r.items()if k!='score'}for r in rows],original)
        self.assertEqual(sorted(rows,key=lambda r:r['elo']),sorted(rows,key=lambda r:r['score']))
        self.assertAlmostEqual((rows[0]['score']+rows[1]['score'])/2,50.)
    def test_location_invariance(self):
        rows=self.rows();normalize(rows,panel=self.panel());before=[r['score']for r in rows]
        for r in rows:r['elo']+=7123
        normalize(rows,panel=self.panel());self.assertEqual(before,[r['score']for r in rows])
    def test_display_and_new_roster_do_not_change_scores(self):
        rows=self.rows();normalize(rows,panel=self.panel());before=[r['score']for r in rows]
        for r in rows:r['papers']=1
        rows.append(dict(model='D',setting='',elo=50000,papers=100))
        normalize(rows,panel=self.panel());self.assertEqual(before,[r['score']for r in rows[:3]])
    def test_missing_reference_is_explicit_without_silent_renormalization(self):
        rows=self.rows()[1:];audit=normalize(rows,panel=self.panel())
        self.assertEqual(audit['status'],'REFERENCE_PANEL_INCOMPLETE');self.assertTrue(all(r['score']is None for r in rows))
    def test_finite_extremes(self):
        rows=self.rows()+[dict(model='Extreme',setting='',elo=1e6,papers=1)]
        normalize(rows,panel=self.panel());self.assertTrue(all(math.isfinite(r['score']) and 0<=r['score']<=100 for r in rows))
    def test_pinned_panel_coverage(self):
        panel=reference_panel()
        self.assertEqual(len(panel['references']),23)
        self.assertTrue(all(min(r['papers'].values())>=10 and not r['setting'] for r in panel['references']))
        self.assertAlmostEqual(sum(r['weight']for r in panel['references']),1.)

if __name__=='__main__':unittest.main()
