from copy import deepcopy
from pathlib import Path
import sys,json,gzip,unittest
sys.path.insert(0,'D:/FDU/benchmark-radar')
import recent_benchmarks
recent_benchmarks.__path__.insert(0,str(Path(__file__).parent/'task_rules'))
from recent_benchmarks.task_constraints import literal_media,literal_access,literal_context
from recent_benchmarks.interactive_profile import CompactProfileClient
from recent_benchmarks.task_labels import build_task_profile,validate_profile,builtin_profile
from recent_benchmarks.catalog_task_scoring import score_task
from recent_benchmarks.task_measurement_policy import task_metric_role,modality_matches
from recent_benchmarks.task_measurements import safe_scores,projection
from test_task_profile_boundaries import Generated,output

class LiteralRequirements(unittest.TestCase):
 def test_exact_media_and_text_surrogates(self):
  for text,expected in [('根据网页截图实现页面','image'),('查看胸部X光影像','image'),('转写会议录音','audio'),('看监控录像','video'),('处理图片和音频输入','audio+image'),('根据音频转写稿整理摘要',None),('生成一张图片',None),('纯文本输入，不用图片','text')]:
   self.assertEqual(literal_media(text),expected,text)
  self.assertFalse(modality_matches('audio',['image','text']))
  self.assertFalse(modality_matches('audio+video',['video']))
  self.assertTrue(modality_matches('audio+video',['video','audio']))
 def test_literal_access_and_context(self):
  for text in ['联网检索新闻','可以联网检索新闻','需要外部检索','search the web']:
   self.assertEqual(literal_access(text),'retrieval')
  self.assertEqual(literal_access('禁止联网，比较给定材料'),'closed_book')
  self.assertIsNone(literal_access('整理医学文献'))
  self.assertIsNone(literal_access('禁止使用工具'))
  self.assertEqual(literal_context('阅读20万 tokens材料',input_context_only=True),200000)
  self.assertEqual(literal_context('阅读200,000 tokens材料',input_context_only=True),200000)
  self.assertIsNone(literal_context('请输出1000 tokens',input_context_only=True))
  self.assertIsNone(literal_context('阅读材料后输出1000 tokens',input_context_only=True))
  self.assertEqual(literal_access('不用联网，核对给定数据'),'closed_book')
  self.assertEqual(literal_access('Do not browse the web'),'closed_book')
  self.assertIsNone(literal_media('不用音频，根据文字稿整理摘要'))
 def test_omitted_and_hallucinated_generated_constraints(self):
  raw=output();raw['constraints']['knowledge_access']='closed_book'
  p=build_task_profile(CompactProfileClient(Generated(raw)),'查看胸部X光影像，描述异常。')
  self.assertEqual(p['constraints']['modality'],'image');self.assertEqual(p['constraints']['knowledge_access'],'any')
  for text in ['联网检索新闻','可以联网检索新闻']:
   p=build_task_profile(CompactProfileClient(Generated(output())),text)
   self.assertEqual(p['constraints']['knowledge_access'],'retrieval')
 def test_manual_requirements_are_not_reinferred_from_description(self):
  p=builtin_profile('code-development');p['description']='根据截图写代码';p['constraints']['modality']='audio+image'
  self.assertEqual(validate_profile(p)['constraints']['modality'],'audio+image')
 def test_derived_rank_only_with_caption_definition(self):
  self.assertEqual(task_metric_role({'metric':'Rank','metric_role_context':'Rows are ordered by the mean of the two scores, and equal displayed scores share a rank.'}),'DERIVED_RANK')
  self.assertEqual(task_metric_role({'metric':'Rank↓','metric_role_context':'Metrics defined in Section 3.5.'}),'PERFORMANCE')

class FrozenRealRequirements(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.root=Path(__file__).parent.parent/'validation';cls.data=json.loads(gzip.decompress((cls.root/'task-comprehensive-task_inputs-20261101.json.gz').read_bytes()))
 def test_pending_protocol_is_a_reference_and_never_a_qualified_recommendation(self):
  p=builtin_profile('code-development');p['constraints']['knowledge_access']='retrieval'
  result=score_task(deepcopy(self.data['index']),self.data['catalog'],p,as_of=self.data['window']['end'])
  self.assertTrue(result['models'])
  self.assertTrue(all(not m['task_eligible'] and m['unverified_constraints']==['knowledge_access'] and m['evidence_kind']=='UNVERIFIED_REFERENCE'for m in result['models']))
  self.assertEqual(result['evidence_summary']['DIRECT_TASK']['models'],0)
 def test_real_rank_projection_and_ambiguous_names(self):
  meta=projection(self.data['index'],self.data['catalog'],self.data['snapshot_id'])
  groups=[g for g in self.data['index']['groups']if 'Launch leaderboard'in g.get('metric_role_context','')and g['metric']=='Rank']
  self.assertEqual(len(groups),8)
  for g in groups:self.assertEqual(meta['groups'][g['group_id']]['capabilities'],[])
  for g in self.data['index']['groups']:
   scores,bad=safe_scores(g,{})
   self.assertFalse(any(s['model_canonical']in {'Flash','0 grok 4.6'}for s in scores))
 def test_candidate_selection_and_source_order_leave_scores_unchanged(self):
  p=builtin_profile('code-development');base=score_task(deepcopy(self.data['index']),self.data['catalog'],p,as_of=self.data['window']['end'])
  names=sorted({m['model_canonical']for m in base['models']})[:7];idx=deepcopy(self.data['index']);idx['groups'].reverse()
  for g in idx['groups']:g['scores'].reverse()
  selected=score_task(idx,list(reversed(self.data['catalog'])),p,candidate_models=list(reversed(names)),as_of=self.data['window']['end'])
  scores={(m['model_canonical'],m['panel_id']):m['score']for m in base['models']}
  self.assertTrue(selected['models'])
  for m in selected['models']:self.assertAlmostEqual(m['score'],scores[m['model_canonical'],m['panel_id']],places=9)

if __name__=='__main__':unittest.main()
