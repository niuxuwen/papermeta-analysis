import unittest
from copy import deepcopy
from source_quality import prepare_data, cell_signature, filter_board_records, attach_provenance
from weighted_bt import pair_records
from build_elo import fit_main_elo

def group(gid='g',metric='Accuracy',setting='',values=(.8,.6)):
    return dict(group_id=gid,paper_id='p',table_id='t',benchmark_id='bench',metric=metric,direction='higher',model_setting=setting,
                scores=[dict(model_canonical=n,value_numeric=v,observation_ids=[gid+n]) for n,v in zip(['A','B'],values)])

def rules(groups,patches=None):
    patches=patches or {}
    return dict(version='test-v1',resource_metrics=['cost ($)','tokens','time (min)'],replacements=[],groups={g['group_id']:{**{k:g[k] for k in ['paper_id','table_id','metric']},'cell_sha256':cell_signature(g),**patches.get(g['group_id'],{})} for g in groups})

def data(gs):return {'index':{'groups':gs}}

class SourceQualityTests(unittest.TestCase):
    def pipeline(self,gs,patches=None):
        d,a=prepare_data(data(gs),rules(gs,patches));r,e=pair_records(d['index']['groups']);return d,attach_provenance(r,d['index']['groups'])
    def test_resource_excluded_but_token_f1_kept(self):
        gs=[group('c','Cost ($)'),group('a','Token F1')];d,r=self.pipeline(gs)
        self.assertEqual([x['group_id'] for x in r],['a'])
        self.assertEqual(len(d['index']['groups']),2)
    def test_raw_values_and_configuration_are_not_mutated(self):
        g=group();old=deepcopy(g);d,r=self.pipeline([g],{'g':{'required_setting':'reasoning effort: low'}})
        self.assertEqual(g,old);self.assertEqual(r[0]['a'][1],'reasoning effort: low')
    def test_explicit_configuration_conflict_is_not_guess_filled(self):
        g=group(setting='reasoning effort: high');d,r=self.pipeline([g],{'g':{'required_setting':'reasoning effort: low'}})
        self.assertFalse(r);self.assertEqual(d['index']['groups'][0]['source_quality']['reason'],'explicit_configuration_conflict')
    def test_bare_effort_conflicts_and_conditions_survive(self):
        g=group(setting='high');d,r=self.pipeline([g],{'g':{'required_setting':'reasoning effort: low'}});self.assertFalse(r)
        g=group(setting='shots: 4');d,r=self.pipeline([g],{'g':{'required_setting':'reasoning effort: low'}})
        self.assertEqual(r[0]['a'][1],'shots: 4; reasoning effort: low')
    def test_explicit_non_performance_role_is_filtered(self):
        g=group(metric='Unfamiliar diagnostic');g['metric_role']='INTERVENTION_EFFECT';d,r=self.pipeline([g]);self.assertFalse(r)
    def test_unreviewed_judge_caption_cannot_set_target_configuration(self):
        g=group();g['metric_role_context']='Judged by a model with reasoning effort high'
        d,r=prepare_data(data([g]),rules([]));self.assertEqual(d['index']['groups'][0]['model_setting'],'')
    def test_changed_source_blocks_stale_override(self):
        g=group();rule=rules([g],{'g':{'direction':'lower'}});g['scores'][0]['value_numeric']=.2
        d,a=prepare_data(data([g]),rule);self.assertFalse(d['index']['groups'][0]['source_quality']['eligible'])
        self.assertEqual(d['index']['groups'][0]['direction'],'higher')
    def test_changed_caption_blocks_stale_configuration(self):
        g=group();g['metric_role_context']='tested at low';rule=rules([g],{'g':{'caption':'tested at low','required_setting':'reasoning effort: low'}})
        g['metric_role_context']='tested at high';d,a=prepare_data(data([g]),rule)
        self.assertFalse(d['index']['groups'][0]['source_quality']['eligible']);self.assertEqual(d['index']['groups'][0]['model_setting'],'')
    def test_configuration_survives_normal_identity_projection(self):
        from model_dedup import project
        g=group();g['scores'][0]['model_canonical']='GPT-5.6-Sol';g['scores'][1]['model_canonical']='Claude 4.7 Opus'
        raw=data([g]);raw['snapshot_id']='test';d,a=prepare_data(raw,rules([g],{'g':{'required_setting':'reasoning effort: low'}}));d,a=project(d)
        rows,_=pair_records(d['index']['groups']);self.assertEqual(len(rows),1)
        self.assertTrue(all('(low)' in n[0] or 'low' in n[1] for n in [rows[0]['a'],rows[0]['b']]))
    def test_repeated_application_is_idempotent(self):
        g=group();rule=rules([g],{'g':{'required_setting':'reasoning effort: low'}})
        d,a=prepare_data(data([g]),rule);d2,a2=prepare_data(d,rule);self.assertEqual(d,d2);self.assertEqual(a,a2)
    def test_direction_flip_preserves_original_values(self):
        g=group();d,r=self.pipeline([g],{'g':{'direction':'lower'}})
        self.assertEqual(r[0]['y'],0);self.assertEqual(d['index']['groups'][0]['scores'],g['scores'])
    def test_aggregate_removal_only_after_board_selection(self):
        gs=[group('total'),group('child')];d,r=self.pipeline(gs,{'child':{'aggregate_parents':['total']}})
        self.assertEqual([x['group_id'] for x in filter_board_records(r)[0]],['total'])
        self.assertEqual([x['group_id'] for x in filter_board_records(r[1:],board='Science')[0]],['child'])
    def test_different_configuration_not_suppressed_by_parent(self):
        gs=[group('total',setting='high'),group('child',setting='low')];d,r=self.pipeline(gs,{'child':{'aggregate_parents':['total']}})
        self.assertEqual(len(filter_board_records(r)[0]),2)
    def test_equal_numbers_are_not_duplicate_evidence(self):
        gs=[group('g1'),group('g2')];d,r=self.pipeline(gs);self.assertEqual(len(filter_board_records(r)[0]),2)
    def test_same_source_cells_cannot_multiply_weight(self):
        g=group();g2=deepcopy(g);g2['group_id']='copy';d,r=self.pipeline([g,g2])
        self.assertEqual(len(filter_board_records(r)[0]),1)
    def test_conflicting_source_cells_fail_loudly(self):
        g=group();g2=deepcopy(g);g2['group_id']='copy';g2['scores'][0]['value_numeric']=.1;d,r=self.pipeline([g,g2])
        with self.assertRaises(ValueError):filter_board_records(r)
    def test_low_coverage_opponents_survive_quality_exclusions(self):
        r=[]
        for i in range(5):
            r.append(dict(a=('A',''),b=('B',''),y=float(i%2),paper_id=str(i),group_id=str(i),benchmark_id='b',source_quality={'eligible':i!=4}))
        eligible,nodes,fit=fit_main_elo(r,{str(i):1. for i in range(5)})
        self.assertEqual(len(eligible),4);self.assertEqual(len(nodes),2);self.assertIsNotNone(fit)
    def test_all_verified_replacement_columns_survive(self):
        g=group();extra=group('singleton');extra['scores']=extra['scores'][:1];rule=rules([g])
        for name in ['P','NPC']:
            rule['replacements'].append(dict(source_groups=['g'],source_table='t',paper_id='p',group_id=name,metric=name,direction='higher',model_setting='',source_url='https://example.org/table',html_sha256='h',source_column=1,scores=[{'model':'A','value':.8},{'model':'B','value':.6}]))
        d,a=prepare_data(data([g,extra]),rule)
        self.assertEqual({x['group_id'] for x in d['index']['groups']},{'g','singleton','P','NPC'})

if __name__=='__main__':unittest.main()
