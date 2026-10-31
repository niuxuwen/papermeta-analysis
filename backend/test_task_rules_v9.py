"""Real snapshot regressions plus boundary checks for task-only policy v9."""
from copy import deepcopy
import gzip,json,sys,unittest
from pathlib import Path

sys.path.insert(0,'D:/FDU/benchmark-radar')
import recent_benchmarks
recent_benchmarks.__path__.insert(0,str(Path(__file__).parent/'task_rules'))
from recent_benchmarks.task_measurement_policy import modality_matches,task_metric_role
from recent_benchmarks.task_measurements import projection
from recent_benchmarks.catalog_task_scoring import score_task,VERSION

class TaskPolicyBoundaryTests(unittest.TestCase):
    def test_modality_umbrella_uses_actual_audited_media_not_text_or_structured_data(self):
        for media in ('image','audio','video'):self.assertTrue(modality_matches('multimodal',[media]))
        self.assertFalse(modality_matches('multimodal',['text','structured_data']))
        self.assertTrue(modality_matches('text',['text','image']))
    def test_color_error_is_not_an_intervention_and_undefined_delta_is_not_task_performance(self):
        self.assertEqual(task_metric_role({'metric':'ΔE00','metric_role_context':'CIEDE2000 color error'}),'PERFORMANCE')
        self.assertEqual(task_metric_role({'metric':'Task-paired delta','metric_role_context':'Task-paired delta'}),'UNRESOLVED_CONTRAST')

class RealTaskPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).parent.parent/'validation'
        p=cls.root/'task-audit-inputs-20261031.json.gz'
        if not p.exists():raise unittest.SkipTest('Real snapshot audit input required')
        cls.raw=p.read_bytes();cls.data=json.loads(gzip.decompress(cls.raw))
        cls.meta=projection(cls.data['index'],cls.data['catalog'],cls.data['snapshot_id'])
    def test_actual_npc_prompt_change_and_jeval_calibration_are_not_task_outcomes(self):
        counts={}
        for g in self.data['index']['groups']:
            if g['benchmark_id']=='bench-0f623769a0e8ec41'and g['metric']in ('Increase','Decrease'):
                self.assertEqual(task_metric_role(g),'INTERVENTION_EFFECT');counts['npc']=True
                self.assertEqual(self.meta['groups'][g['group_id']]['capabilities'],[])
            if g['benchmark_id']=='bench-2e6368133fde084e'and g['metric'].startswith('ECE'):
                self.assertEqual(task_metric_role(g),'CALIBRATION_DIAGNOSTIC');counts['ece']=True
        self.assertEqual(set(counts),{'npc','ece'})
    def test_actual_visual_profile_no_longer_loses_all_image_measurements(self):
        old=json.loads(gzip.decompress((self.root/'task-audit-visual-20261031.json.gz').read_bytes()))['task_index']
        self.assertEqual(old['matched_benchmarks'],0)
        result=score_task(deepcopy(self.data['index']),self.data['catalog'],old['profile'],min_benchmarks=1)
        self.assertGreater(result['matched_benchmarks'],0)
        ids={(b['paper_id'],b['benchmark_id'])for b in result['benchmark_matches']}
        self.assertTrue(all(set(b['catalog_labels']['modalities'])&{'image','audio','video'}for b in self.data['catalog']if(b['paper_id'],b['benchmark_id'])in ids))
    def test_medical_results_separate_references_and_keep_exact_raw_values_and_subset_scores(self):
        profile=json.loads(gzip.decompress((self.root/'task-audit-medical-20261031.json.gz').read_bytes()))['task_index']['profile']
        before=json.dumps(self.data,sort_keys=True)
        full=score_task(deepcopy(self.data['index']),self.data['catalog'],profile,min_benchmarks=1)
        self.assertGreaterEqual(VERSION,9);self.assertEqual(full['evidence_summary']['DIRECT_TASK']['benchmarks'],0)
        self.assertGreater(full['evidence_summary']['RELATED_REFERENCE']['benchmarks'],0)
        groups={g['group_id']:g for g in self.data['index']['groups']}
        for m in full['models']:
            self.assertEqual(m['evidence_kind'],'RELATED_REFERENCE')
            for c in m['score_components']:
                g=groups[c['group_id']];self.assertEqual(task_metric_role(g),'PERFORMANCE')
                self.assertIn(c['raw_value'],[s['value_numeric']for s in g['scores']if s['model_canonical']==m['model_canonical']])
        names=list(dict.fromkeys(m['model_canonical']for m in full['models']))[:2]
        selected=score_task(deepcopy(self.data['index']),self.data['catalog'],profile,min_benchmarks=1,candidate_models=names)
        allscores={(m['panel_id'],m['model_canonical']):m['score']for m in full['models']}
        self.assertTrue(selected['models'])
        for m in selected['models']:self.assertEqual(m['score'],allscores[m['panel_id'],m['model_canonical']])
        self.assertEqual(json.dumps(self.data,sort_keys=True),before)

if __name__=='__main__':unittest.main()
