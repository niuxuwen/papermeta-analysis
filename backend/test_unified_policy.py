import unittest,json,gzip,sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).parent.parent
sys.path.insert(0,'D:/FDU/benchmark-radar')
import recent_benchmarks
recent_benchmarks.__path__.insert(0,str(ROOT/'backend/task_rules'))
from recent_benchmarks.common_source_calibration import attach,CALIBRATION,pair_summaries
from recent_benchmarks.global_scoring import comparison_target
from recent_benchmarks.task_measurement_policy import task_metric_role
from recent_benchmarks.task_measurements import inspect

class UnifiedPolicy(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads(gzip.decompress((ROOT/'validation/completeness-task_inputs-20261031.json.gz').read_bytes()))
 def test_general_subset_does_not_inherit_medical_task_from_other_tables(self):
  g=next(g for g in self.data['index']['groups']if g['group_id']=='149043c6feb39d84bfd245d3')
  b=next(b for b in self.data['catalog']if b['benchmark_id']==g['benchmark_id'])
  b={**b,'matched_capabilities':['domain_knowledge']}
  for domain in ['medicine','law','finance']:
   m=inspect(g,b,{'domains':[domain],'tasks':['knowledge_qa']})
   self.assertEqual(m['basis'],'CATALOG_RELATED_REFERENCE');self.assertTrue(m['facet'].startswith('related_reference:'))
 def test_actual_displacement_prediction_error_is_an_outcome(self):
  groups=[g for g in self.data['index']['groups']if g['metric'].startswith('∆x')]
  self.assertTrue(groups)
  for g in groups:self.assertEqual(task_metric_role(g),'PERFORMANCE')
 def test_uniform_calibration_never_uses_manufacturer(self):
  self.assertFalse(CALIBRATION['vendor_grouping_used']);self.assertEqual(CALIBRATION['within_vendor_strength'],0)
  old=json.load(gzip.open('D:/FDU/benchmark-radar/dist/public-v119-snapshot-20261028.json.gz','rt',encoding='utf-8'))
  groups=[g for g in old['index']['groups']if not g['model_setting']and g.get('global_status')=='CORE_READY']
  names=['GPT-5.6-Sol','GPT-6-Sol'];groups=[{**g,'scores':[s for s in g['scores']if s['model_canonical']in names]}for g in groups]
  groups=[g for g in groups if len(g['scores'])==2]
  self.assertGreaterEqual(pair_summaries(groups,names,comparison_target)[0]['papers'],2)
  def applied(gs,ns):
   layout={'edges':[],'clusters':{},'priors':[.3,.3]};r=attach(layout,gs,ns,ns,comparison_target,1)
   self.assertFalse(layout['quadratic_edges']);self.assertTrue(r['direct_terms']);return layout['edges']
  first=applied(groups,names);renamed=deepcopy(groups);mapping={names[0]:'AA Other Vendor 1',names[1]:'ZZ Other Vendor 2'}
  for g in renamed:
   for s in g['scores']:s['model_canonical']=mapping[s['model_canonical']]
  self.assertEqual(first,applied(renamed,[mapping[n]for n in names]))

if __name__=='__main__':unittest.main()
