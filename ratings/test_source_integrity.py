import unittest
from copy import deepcopy
from collections import defaultdict
from source_integrity import reconcile_roster,apply_repairs,signature
from effort_projection import pool_efforts

def edge(a,b,g,p='p',y=1):
    return dict(a=(a,''),b=(b,''),group_id=g,paper_id=p,benchmark_id='bench',y=y)

class IntegrityTests(unittest.TestCase):
    def test_missing_opponent_is_visible(self):
        audit=reconcile_roster(['A','B','C'],[dict(model_canonical='A'),dict(model_canonical='B')])
        self.assertEqual(audit['missing'],['C'])
        self.assertEqual(reconcile_roster(['A'],[],{'A':''})['missing'],['A'])
    def test_verified_rosters_reach_comparison_projection(self):
        import json
        from pathlib import Path
        rules=json.loads(Path(__file__).with_name('source-integrity-registry.json').read_text(encoding='utf8'))
        for gid,spec in rules['groups'].items():
            if not spec.get('scores') or spec.get('metadata'):continue
            g=dict(group_id=gid,paper_id=spec['paper_id'],table_id=spec['table_id'],scores=[dict(model_canonical='MiMo V2.6 Pro',value_numeric=71.9),dict(model_canonical='MiMo V2.6 Flash',value_numeric=67.9)])
            data={'index':{'groups':[g]},'measurements':{'groups':{gid:{'models':['MiMo V2.6 Pro','MiMo V2.6 Flash']}}}}
            events=apply_repairs(data,rules)
            self.assertEqual(events[0]['status'],'REPAIRED')
            self.assertEqual(len(g['scores']),len(spec['expected_models']))
            self.assertIn('GPT-5.6-Sol',data['measurements']['groups'][gid]['models'])
            self.assertIn('Claude 5 Opus',data['measurements']['groups'][gid]['models'])
            self.assertEqual(len(g['pre_repair_scores']),2)
    def test_repeat_metrics_cannot_multiply_mass(self):
        base=[edge('A','B','g')];many=[edge('A','B',str(i)) for i in range(20)]
        _,b,_,_=pool_efforts(base,{'p':.4});_,m,_,_=pool_efforts(many,{'p':.4})
        self.assertAlmostEqual(b[0]['weight'],m[0]['weight'])
        self.assertEqual(b[0]['y'],m[0]['y'])
    def test_metric_direction_and_supplemental_group_preserve_evidence(self):
        g=dict(group_id='g',paper_id='p',table_id='t',metric='Severity',direction='lower',scores=[dict(model_canonical='A',value_numeric=11),dict(model_canonical='B',value_numeric=69)])
        spec=dict(paper_id='p',table_id='t',cell_sha256=signature(g),scores=deepcopy(g['scores']),expected_models=['A','B'],
            metadata={'metric':'No-concern replies (%)','direction':'higher'},source_url='url',source_sha256='sha',explanation='verified segment',
            additional_groups=[dict(group_id='g2',metric='MHQR',direction='lower',scores=[dict(model_canonical='A',value_numeric=4.31),dict(model_canonical='B',value_numeric=.91)])])
        data={'index':{'groups':[deepcopy(g)]},'measurements':{'groups':{'g':{'capabilities':['safety'],'models':['A','B']}}}}
        rules={'version':'v','groups':{'g':spec}}
        apply_repairs(data,rules)
        self.assertEqual(data['index']['groups'][0]['pre_repair_metadata']['direction'],'lower')
        self.assertEqual(data['index']['groups'][0]['direction'],'higher')
        self.assertEqual(data['measurements']['groups']['g2']['models'],['A','B'])
        self.assertEqual(data['index']['groups'][0]['pre_repair_scores'],g['scores'])
        apply_repairs(data,rules)
        self.assertEqual(len(data['index']['groups']),2)
    def test_reviewed_semantics_registry_has_complete_tables(self):
        import json
        from pathlib import Path
        rules=json.loads(Path(__file__).with_name('source-integrity-registry.json').read_text(encoding='utf8'))['groups']
        mind=rules['afcb25208a05a3db07fd2c0b']
        self.assertEqual(mind['metadata']['direction'],'higher')
        self.assertEqual(len(mind['scores']),18)
        values={s['model_canonical']:s['value_numeric'] for s in mind['scores']}
        self.assertLess(values['Muse Glimmer 30B'],values['GPT-5.6-Sol'])
        self.assertEqual(mind['additional_groups'][0]['direction'],'lower')
        for gid in ('e9befe772527a3142dba2117','b39f358ea7bf78489ff3a907'):
            r=rules[gid]
            self.assertEqual(len(r['scores']),9)
            self.assertEqual(len(r['additional_groups']),3)
            for extra in r['additional_groups']:
                self.assertEqual(len(extra['scores']),9)
                self.assertEqual(extra['evaluation_condition'],r['metadata']['evaluation_condition'])
    def test_disjoint_opponents_share_paper_budget(self):
        es=[edge('A',str(i),str(i)) for i in range(10)]
        _,obs,_,_=pool_efforts(es,{'p':.4})
        self.assertLessEqual(sum(r['weight'] for r in obs),.40000001)
    def test_code2video_column_alignment_and_complete_rosters(self):
        import json
        from pathlib import Path
        rules=json.loads(Path(__file__).with_name('source-integrity-registry.json').read_text(encoding='utf8'))['groups']
        for gid,expected in [('1a09dc5fafbeaf05ec5ff45b',.568),('4ad4e4e1d91ce10c640886c5',.473),('86e87dc41387970e63993383',.863)]:
            rule=rules[gid]
            values={s['model_canonical']:s['value_numeric'] for s in rule['scores']}
            self.assertEqual(len(values),15)
            self.assertEqual(values['MiMo V2.6 Pro'],expected)
            self.assertIn('Claude 5.5 Opus',values)
            self.assertIn('GPT-6.1-Sol',values)
            self.assertIn('Kimi K3',values)
            self.assertTrue(all(s['task_source_records'][0]['html_cell_id'] for s in rule['scores']))
        for gid in ('f7170b5839ba7abfc7592ae0','c1c22f06d5cab956ee13e65a'):
            self.assertTrue(rules[gid]['annotation_only'])
    def test_spatial_main_table_has_all_nine_endpoints(self):
        import json
        from pathlib import Path
        rule=json.loads(Path(__file__).with_name('source-integrity-registry.json').read_text(encoding='utf8'))['groups']['aead4e55a2c57421a1e331ea']
        self.assertEqual(len(rule['scores']),9)
        self.assertEqual(len(rule['additional_groups']),8)
        self.assertEqual(len({g['metric'] for g in rule['additional_groups']}),8)
        self.assertTrue(all(len(g['scores'])==9 for g in rule['additional_groups']))
    def test_tigan_full_table_supersedes_only_overlapping_subset(self):
        import json
        from pathlib import Path
        from source_quality import filter_board_records
        rules=json.loads(Path(__file__).with_name('source-integrity-registry.json').read_text(encoding='utf8'))['groups']
        rule=rules['3e1d8c526d42904c76981055']
        self.assertEqual(len(rule['additional_groups']),10)
        byid={g['group_id']:g for g in rule['additional_groups']}
        success=byid['tigan-all64-8-v3']
        vals={s['model_canonical']:s['value_numeric'] for s in success['scores']}
        self.assertEqual(vals['MiMo V2.6 Pro'],62.5)
        self.assertEqual(vals['GPT-5.6-Sol'],29.7)
        self.assertEqual(success['evaluation_n'],64)
        self.assertTrue(success['source_integrity_evidence']['source_url'].endswith('#S5.T4'))
        child=dict(edge('A','B','subset'),source_quality={'aggregate_parents':['parent']})
        parent=edge('A','B','parent')
        self.assertEqual([e['group_id'] for e in filter_board_records([child,parent])[0]],['parent'])
        self.assertEqual([e['group_id'] for e in filter_board_records([child])[0]],['subset'])
    def test_subdividing_one_benchmark_does_not_outvote_another(self):
        es=[dict(edge('A','B',str(i),y=1),benchmark_id='b1') for i in range(20)]
        es.append(dict(edge('A','B','other',y=0),benchmark_id='b2'))
        _,obs,_,_=pool_efforts(es,{'p':.4})
        self.assertAlmostEqual(obs[0]['y'],.5)
    def test_unknown_independent_sources_remain_distinct(self):
        _,obs,_,audit=pool_efforts([edge('A','B','g','p'),edge('A','B','g','q')],{'p':.4,'q':.4})
        self.assertEqual(len(obs),2)
        self.assertAlmostEqual(sum(r['weight'] for r in obs),.8)
        for model in audit['source_concentration']:
            self.assertAlmostEqual(model['largest_source_share'],.5)
            self.assertAlmostEqual(model['effective_sources'],2.)
    def test_verified_shared_source_keeps_papers_without_extra_budget(self):
        es=[dict(edge('A','B','g',p),source_quality={'evidence_source_id':'shared'}) for p in ('p','q')]
        kept,obs,_,_=pool_efforts(es,{'p':.4,'q':.4})
        self.assertEqual({e['paper_id'] for e in kept},{'p','q'})
        self.assertAlmostEqual(sum(r['weight'] for r in obs),.4)
    def test_changed_source_cannot_silently_reuse_repair(self):
        g=dict(group_id='g',paper_id='p',table_id='t',scores=[dict(model_canonical='A',value_numeric=1)])
        rule=dict(paper_id='p',table_id='t',cell_sha256=signature(g),annotation_only=True,source_url='u',source_sha256='s',explanation='delta')
        data={'index':{'groups':[deepcopy(g)]}}
        apply_repairs(data,{'version':'v','groups':{'g':rule}})
        self.assertEqual(data['index']['groups'][0]['scores'],g['scores'])
        self.assertFalse(data['index']['groups'][0]['source_quality']['eligible'])
        data['index']['groups'][0].pop('source_integrity_revision');data['index']['groups'][0]['scores'][0]['value_numeric']=2
        self.assertEqual(apply_repairs(data,{'version':'v','groups':{'g':rule}})[0]['status'],'SOURCE_CHANGED')

if __name__=='__main__':unittest.main()
