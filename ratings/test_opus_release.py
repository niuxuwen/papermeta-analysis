import unittest
from build_elo import fit_main_elo
from source_quality import filter_board_records

def e(a,b,y,g):
    return dict(a=(a,''),b=(b,''),y=y,paper_id='p',group_id=g,benchmark_id='b')

class OpusReleaseTests(unittest.TestCase):
    def test_undefeated_effort_wins_survive_core_selection(self):
        rows=[e('GPT-6-Astra','Claude 5.5 Opus',1,'g1'),e('Claude 5.5 Opus','GPT-5.6-Sol',1,'g2'),e('GPT-5.6-Sol','GPT-6-Astra',1,'g3'),e('Claude 5.5 Opus adaptive/Max','GPT-6-Astra',1,'g4')]
        kept,nodes,fit=fit_main_elo(rows,{'p':1})
        self.assertEqual(len(kept),4)
        self.assertIn(('Claude 5.5 Opus',''),nodes)
        self.assertFalse(any('adaptive' in n[0] for n in nodes))
        self.assertTrue(fit['optimizer']['success'])
        self.assertTrue(all(r['fit_weight']>0 for r in kept))
    def test_repeated_batch_preserves_unshared_opponents(self):
        primary=e('A','B',1,'main'); repeat=e('A','B',1,'copy'); unique=e('A','C',1,'copy')
        for r in (repeat,unique):r['source_quality']={'aggregate_parents':['main']}
        kept,_=filter_board_records([primary,repeat,unique])
        self.assertEqual(kept,[primary,unique])

if __name__=='__main__':unittest.main()
