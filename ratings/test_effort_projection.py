import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from effort_projection import base_node,pool_efforts

def edge(a,b,y=1,p='p',g='g'):
    return dict(a=(a,''),b=(b,''),y=y,paper_id=p,group_id=g,benchmark_id='b',w=1,beta=1)

class EffortTest(unittest.TestCase):
    def test_explicit_levels(self):
        for name in ['GPT-6-Astra (max)','GPT-6-Astra (medium)','GPT-6-Astra (low)']:
            self.assertEqual(base_node((name,'')),('GPT-6-Astra',''))
        self.assertEqual(base_node(('Claude 5 Opus adaptive/Max','reasoning effort: medium | tools enabled')),('Claude 5 Opus','tools enabled'))
    def test_preserve_product_and_protocol(self):
        for name in ['Qwen 3.8 Max','Mistral Medium 3.5','DeepSeek-Reasoner','GLM 5.3 Max','Gemini 3.1 Pro Preview','Qwen 3 4B Thinking 2507']:
            self.assertEqual(base_node((name,'tools on')), (name,'tools on'))
    def test_variants_do_not_multiply_budget(self):
        baseline=[edge('GPT-6-Astra','Claude 5 Opus',1)]
        duplicated=[edge('GPT-6-Astra (high)','Claude 5 Opus',1,g='high'),edge('GPT-6-Astra (low)','Claude 5 Opus',1,g='low'),edge('GPT-6-Astra (medium)','Claude 5 Opus',1,g='medium')]
        _,b,_,_=pool_efforts(baseline,{'p':.4})
        _,d,_,_=pool_efforts(duplicated,{'p':.4})
        self.assertEqual(len(d),1)
        self.assertAlmostEqual(b[0]['weight'],d[0]['weight'])
        self.assertAlmostEqual(b[0]['y'],d[0]['y'])
    def test_mixed_outcomes_average_not_best(self):
        records=[edge('GPT-6-Astra (high)','Claude 5 Opus',1,g='h'),edge('GPT-6-Astra (low)','Claude 5 Opus',0,g='l')]
        _,obs,_,_=pool_efforts(records,{'p':.4})
        self.assertEqual(obs[0]['y'],.5)
    def test_self_match_not_fake_evidence(self):
        records=[edge('GPT-6-Astra (high)','GPT-6-Astra (low)',1)]
        projected,obs,_,audit=pool_efforts(records,{'p':.4})
        self.assertEqual(obs,[])
        self.assertEqual(audit['only_within_model_papers'],['p'])
        self.assertEqual(audit['self_comparisons'],1)
    def test_independent_papers_stay_independent(self):
        records=[edge('GPT-6-Astra (high)','Claude 5 Opus',1,p='a'),edge('GPT-6-Astra (low)','Claude 5 Opus',1,p='b')]
        _,obs,_,_=pool_efforts(records,{'a':.4,'b':.4})
        self.assertEqual(len(obs),2)
    def test_other_settings_and_sizes_not_combined(self):
        records=[edge('GPT-6-Astra (high)','Qwen 2.5 7B'),edge('GPT-6-Astra (low)','Qwen 2.5 72B',g='h')]
        records[1]['a']=('GPT-6-Astra (low)','tools enabled')
        _,_,m,_=pool_efforts(records,{'p':.4})
        self.assertNotEqual(m[records[0]['a']],m[records[1]['a']])
        self.assertNotEqual(m[records[0]['b']],m[records[1]['b']])
    def test_measurements_average_before_paper_incident_budget(self):
        from collections import Counter,defaultdict
        import math
        records=[edge('GPT-6-Astra','Claude 5 Opus',1,g='a'),edge('GPT-6-Astra','Claude 5 Opus',0,g='b'),edge('GPT-6-Astra','Gemini 3.1 Pro',1,g='b'),edge('Claude 5 Opus','Gemini 3.1 Pro',1,g='b')]
        _,obs,_,_=pool_efforts(records,{'p':.4})
        original={}
        groups=defaultdict(set)
        for e in records:groups[e['group_id']].update((e['a'],e['b']))
        count=Counter(tuple(sorted((e['a'],e['b']))) for e in records)
        for e in records:
            a,b=sorted((e['a'],e['b']));y=e['y'] if a==e['a'] else 1-e['y']
            w=.4/(len(groups[e['group_id']])-1)/count[a,b]
            mass,win=original.get((a,b),(0,0));original[a,b]=(mass+w,win+w*y)
        incident={}
        for (a,b),(mass,win) in original.items():
            incident[a]=incident.get(a,0)+mass;incident[b]=incident.get(b,0)+mass
        factor=min(1.,.4/max(incident.values()))
        for r in obs:
            mass,win=original[r['a'],r['b']]
            self.assertAlmostEqual(r['weight'],mass*factor)
            self.assertAlmostEqual(r['y'],win/mass)

if __name__=='__main__':unittest.main()
