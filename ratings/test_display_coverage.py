import unittest
from copy import deepcopy
from build_elo import fit_main_elo,coverage_audit
from fit import export
from build_capability_rankings import add_category_scores

def edge(p,a,b,y):
    return dict(paper_id=p,group_id=p+a+b,benchmark_id=p,a=(a,''),b=(b,''),y=y)

class DisplayCoverageTests(unittest.TestCase):
    def fixture(self):
        rows=[edge(str(i),'A','B',float(i%2)) for i in range(6)]
        rows += [edge('rare','A','C',1.),edge('rare','B','C',0.)]
        return rows,{r['paper_id']:1. for r in rows}
    def test_rare_opponent_and_its_paper_remain_in_fit(self):
        rows,q=self.fixture();old=deepcopy(rows)
        kept,nodes,fit=fit_main_elo(rows,q,min_papers=5)
        self.assertEqual([{k:r[k] for k in rows[0]} for r in kept],rows);self.assertIn(('C',''),nodes);self.assertEqual(rows,old)
        result=export(fit,kept,['A','B']);c=next(r for r in result if r['model']=='C')
        self.assertEqual(c['papers'],1)
        self.assertEqual(coverage_audit(rows,kept)['coverage_removed_papers'],0)
    def test_display_minimum_cannot_change_strengths_or_papers(self):
        rows,q=self.fixture()
        r1,n1,f1=fit_main_elo(rows,q,min_papers=1)
        r5,n5,f5=fit_main_elo(rows,q,min_papers=7)
        self.assertEqual(r1,r5);self.assertEqual(n1,n5);self.assertEqual(f1['theta'],f5['theta'])
    def test_rare_opponent_changes_estimated_comparison(self):
        rows,q=self.fixture();_,_,full=fit_main_elo(rows,q)
        _,_,without=fit_main_elo(rows[:6],q)
        self.assertGreater(abs((full['theta'][('A','')]-full['theta'][('B','')])-(without['theta'][('A','')]-without['theta'][('B','')])),.01)
    def test_coverage_does_not_mask_unconnected_evidence(self):
        rows,q=self.fixture();rows += [edge('other','D','E',.5)];q['other']=1.
        kept,_,_=fit_main_elo(rows,q)
        audit=coverage_audit(rows,kept)
        self.assertEqual(audit['retained_papers'],8)
        self.assertEqual(audit['outside_global_component_papers'],['other'])
        self.assertEqual(audit['coverage_removed_papers'],0)
    def test_category_elo_is_independent_of_display(self):
        rows=[dict(model='A',papers=5,elo=1200),dict(model='B',papers=5,elo=1000),dict(model='C',papers=1,elo=1600)]
        panel=dict(version='test',references=[dict(model='A',weight=.5),dict(model='B',weight=.5)])
        add_category_scores(rows,panel)
        self.assertEqual([r['score'] for r in rows],[1100,900,1500])
        self.assertEqual(len(rows),3);self.assertIsNotNone(rows[2]['score'])
        before=[r['score'] for r in rows]
        for row in rows:row['papers']=1
        add_category_scores(rows,panel)
        self.assertEqual(before,[r['score']for r in rows])

if __name__=='__main__':unittest.main()
