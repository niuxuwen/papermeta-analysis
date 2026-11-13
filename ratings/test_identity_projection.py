import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from identity_projection import project_edges

def edge(a,b,y=1,p='p',g='g'):
    return dict(a=(a,''),b=(b,''),y=y,paper_id=p,group_id=g,benchmark_id='b',w=1,beta=1)

class IdentityTest(unittest.TestCase):
    def test_scale_named_gpt_oss(self):
        _,m,_=project_edges([edge(n,'Claude 5 Opus',p=str(i)) for i,n in enumerate(['GPT OSS 120B','GPT-OSS-120B','GPT-OSS 120B','GPT-OSS-20B'])])
        self.assertEqual(m['GPT OSS 120B',''],m['GPT-OSS-120B',''])
        self.assertNotEqual(m['GPT OSS 120B',''],m['GPT-OSS-20B',''])
    def test_batch_aliases(self):
        out,m,a=project_edges([edge('GPT6 Astra','Claude 5 Opus'),edge('GPT-6-Astra','Claude5 Opus',p='q')],['GPT-6-Astra'])
        self.assertEqual(m['GPT6 Astra',''],('GPT-6-Astra',''))
        self.assertEqual(len({r[k]for r in out for k in ('a','b')}),2)
        self.assertEqual(a['papers_after'],2)
    def test_protected_variants(self):
        names=['GPT-5.6-Sol','GPT-5.6-Sol (max)','GPT-5.6-Sol (medium)','GPT-5.6-Terra','Gemini 3.1 Pro','Gemini 3.1 Pro Preview','Qwen 2.5 7B','Qwen 2.5 72B','Qwen 2.5 7B Instruct']
        _,m,_=project_edges([edge(n,'GPT-4o',p=str(i)) for i,n in enumerate(names)])
        self.assertEqual(len({m[n,'']for n in names}),len(names))
    def test_same_group_tie_collapses_once(self):
        out,_,a=project_edges([edge('GPT6 Astra','GPT-6-Astra',.5),edge('GPT6 Astra','Claude 5 Opus'),edge('GPT-6-Astra','Claude 5 Opus')])
        self.assertEqual(len(out),1)
        self.assertEqual(len(a['duplicate_comparisons']),1)
        self.assertEqual(len(a['self_comparisons']),1)
    def test_conflict_preserves_paper_and_peers(self):
        inp=[edge('GPT6 Astra','GPT-6-Astra'),edge('GPT6 Astra','Claude 5 Opus'),edge('GPT-6-Astra','Claude 5 Opus',0),edge('Claude 5 Opus','Gemini 3.1 Pro')]
        out,m,a=project_edges(inp)
        self.assertNotEqual(m['GPT6 Astra',''],m['GPT-6-Astra',''])
        self.assertEqual(len(out),4)
        self.assertTrue(a['conflicts'])
    def test_same_result_different_paper_is_not_duplicate(self):
        out,_,_=project_edges([edge('GPT6 Astra','Claude 5 Opus',p='p'),edge('GPT-6-Astra','Claude 5 Opus',p='q')])
        self.assertEqual(len(out),2)
    def test_soft_complement_roundoff_does_not_block_identity_merge(self):
        out,_,audit=project_edges([edge('GPT6 Astra','Claude 5 Opus',.8),
                                  edge('GPT-6-Astra','Claude 5 Opus',1-(1-.8)+1e-16)])
        self.assertEqual(len(out),1)
        self.assertFalse(audit['conflicts'])
    def test_unknown_config_kept(self):
        a=edge('GPT-6-Astra','Claude 5 Opus');b=edge('GPT-6-Astra','Claude 5 Opus',p='q');b['a']=('GPT-6-Astra','tools enabled')
        _,m,_=project_edges([a,b])
        self.assertNotEqual(m[tuple(a['a'])],m[tuple(b['a'])])

if __name__=='__main__':unittest.main()
