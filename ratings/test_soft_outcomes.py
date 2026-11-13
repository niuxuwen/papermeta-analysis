import math
import unittest
from soft_outcomes import outcome, rms_scales
from weighted_bt import pair_records


def group(values, **kw):
    return dict(group_id='g', paper_id='p', benchmark_id='bench', table_id='t',
                metric='accuracy (%)', direction='higher',
                scores=[dict(model_canonical=str(i), value_numeric=x) for i,x in enumerate(values)], **kw)


class SoftOutcomeTests(unittest.TestCase):
    def test_pdf_binomial_example_and_n_sensitivity(self):
        results=[]
        for n in [100,1000]:
            g=group([80,75], evaluation_n=n, sample_size=dict(status='SOURCE_REVIEWED',scope='evaluated_subset',n=n))
            rs,_=pair_records([g],soft=True)
            results.append(rs[0]['y'])
            self.assertEqual(rs[0]['outcome_audit']['method'],'binomial_independent_approximation')
        self.assertAlmostEqual(results[0],.8018,places=3)
        self.assertGreater(results[1],.996)

    def test_unknown_n_not_fabricated(self):
        g=group([80,75],evaluation_n=100)
        rs,_=pair_records([g],soft=True)
        self.assertEqual(rs[0]['outcome_audit']['method'],'empirical_rms')
        self.assertAlmostEqual(rs[0]['y'],.8413447460685429)

    def test_nonbinary_metric_with_n_uses_rms(self):
        g=group([80,75],evaluation_n=100,sample_size=dict(status='SOURCE_REVIEWED',scope='evaluated_subset',n=100))
        g['metric']='F1 (%)'
        rs,_=pair_records([g],soft=True)
        self.assertEqual(rs[0]['outcome_audit']['method'],'empirical_rms')

    def test_symmetry_ties_and_direction(self):
        g=group([80,75]);scales=rms_scales([(g,g['scores'])]);a,b=g['scores']
        self.assertAlmostEqual(sum(outcome(g,x,y,scales)[0] for x,y in [(a,b),(b,a)]),1)
        self.assertEqual(outcome(g,a,a,scales)[0],.5)
        g['direction']='lower';scales=rms_scales([(g,g['scores'])])
        self.assertLess(outcome(g,a,b,scales)[0],.5)

    def test_empirical_scale_unit_and_duplicate_invariance(self):
        a=group([20,25,90]);b=group([.2,.25,.9])
        x,_=pair_records([a],soft=True);y,_=pair_records([b],soft=True)
        self.assertEqual(len(x),3)
        for u,v in zip(x,y):self.assertAlmostEqual(u['y'],v['y'])
        self.assertEqual(rms_scales([(a,a['scores'])]),rms_scales([(a,a['scores'])]*2))

    def test_elo_link_and_all_ties(self):
        g=group([1400,1000]);g['metric']='Arena Elo'
        rs,_=pair_records([g],soft=True)
        self.assertAlmostEqual(rs[0]['y'],10/11)
        g=group([7,7,7]);rs,_=pair_records([g],soft=True)
        self.assertTrue(all(r['y']==.5 for r in rs))

    def test_excluded_sources_do_not_change_rms(self):
        a=group([80,75]);b=group([1,10000]);b['blocked_reasons']=['BAD']
        x,_=pair_records([a],soft=True);y,_=pair_records([a,b],soft=True)
        self.assertEqual(x,y)

    def test_reviewed_alias_preserves_soft_outcomes(self):
        from alias_projection import project_records
        from rank_review import validate_edges
        g=group([80,75,65]);g['scores'][0]['model_canonical']='Fable 5'
        rows,_=pair_records([g],soft=True)
        rows=[dict(r,q=1) for r in rows]
        registry={('p','Fable 5',''):dict(canonical_name='Claude Fable 5',configuration=None)}
        mapped,_=project_records(dict(snapshot_id='s',index=dict(groups=[g])),rows,registry)
        validate_edges(mapped)
        self.assertEqual(len(mapped),3)
        for r in mapped:
            original=next(x for x in rows if x['outcome_audit']==r['outcome_audit'])
            if r['a'][0]==original['a'][0] or (r['a'][0]=='Claude Fable 5' and original['a'][0]=='Fable 5'):
                self.assertAlmostEqual(r['y'],original['y'])
            else:self.assertAlmostEqual(r['y'],1-original['y'])
            self.assertNotIn(r['y'],[0,1])


if __name__=='__main__':unittest.main()
