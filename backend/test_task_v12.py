import gzip,json,sys,unittest
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,'D:/FDU/benchmark-radar')
import recent_benchmarks
recent_benchmarks.__path__.insert(0,str(Path(__file__).parent/'task_rules'))
from recent_benchmarks.task_constraints import literal_media,literal_access
from recent_benchmarks.task_measurements import source_model_identity_issue,inspect,safe_scores
from recent_benchmarks.task_measurement_policy import task_metric_role
from recent_benchmarks.interactive_profile import CompactProfileClient
from recent_benchmarks.task_labels import build_task_profile
from test_task_profile_boundaries import Generated,output
ROOT=Path(__file__).parent.parent/'validation'

class InputOutputScope(unittest.TestCase):
 def test_all_observed_parser_counterexamples(self):
  data=json.loads((ROOT/'task-readiness-followup-20261101.json').read_text(encoding='utf-8'))
  for c in data['lexical_controls']:
   with self.subTest(description=c['description']):
    self.assertEqual((literal_media if c['kind']=='media'else literal_access)(c['description']),c['expected'])
 def test_input_and_output_scope_in_both_orders(self):
  cases=[('读取图片，只输出纯文本摘要','image'),('结果仅文本输出，阅读这张截图','image'),('输出JSON并分析输入图片','image'),('根据已生成的图片分析颜色','image'),('根据录音生成视频','audio'),('只用纯文本输入，生成一段语音','text'),('Read an image and output text only','image'),('Return text only after reading an image','image'),('输入为音频，输出为图片','audio'),('只处理视频，不接收原始音频','video'),('仅文本输入，不用图片','text')]
  for text,expected in cases:
   with self.subTest(description=text):self.assertEqual(literal_media(text),expected)
 def test_transcripts_and_unprovided_media(self):
  for text in ['根据会议录音的逐字稿整理纪要，不需要处理音频','输入是视频的文字描述，不提供视频文件','总结音频转录稿，不接收原始音频','summarize a transcript of the audio without audio']:
   with self.subTest(description=text):self.assertIsNone(literal_media(text))
 def test_generated_profile_keeps_literal_input_even_if_provider_reports_text_output(self):
  raw=output();raw['constraints']['modality']='text'
  p=build_task_profile(CompactProfileClient(Generated(raw)),'分析输入图片，输出纯文本摘要。')
  self.assertEqual(p['constraints']['modality'],'image')
 def test_browser_retrieval_and_local_retrieval_are_not_closed_book(self):
  for text in ['必须使用浏览器检索新闻并提供来源链接','通过搜索引擎查找资料','禁止联网，只允许本地检索给定文档']:
   with self.subTest(description=text):self.assertEqual(literal_access(text),'retrieval')

class SourceIdentityReview(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads(gzip.decompress((ROOT/'task-readiness-followup-inputs.json.gz').read_bytes()))
  cls.review=json.loads((ROOT/'task-readiness-followup-20261101.json').read_text(encoding='utf-8'))
 def test_all_twelve_reviewed_labels_are_kept_out_of_definite_model_scores(self):
  for name in self.review['identity_review']:
   with self.subTest(name=name):self.assertIsNotNone(source_model_identity_issue(name))
  for g in self.data['index']['groups']:
   kept,bad=safe_scores(g,{})
   self.assertTrue(all(s['model_canonical']not in self.review['identity_review']for s in kept))
 def test_complete_known_labels_are_not_removed_by_vendor_or_version(self):
  for n in ['GPT-5.6-Sol','GPT-6-Astra','Gemini 3.8 Flash','Claude 5.5 Opus','Qwen 3.5 397B A17B','DeepSeek-V4.1-Flash']:
   self.assertIsNone(source_model_identity_issue(n))
 def test_caption_defined_rank_aliases_and_privacy_measurement_scope(self):
  found=0
  for g in self.data['index']['groups']:
   text=g.get('metric_role_context','').casefold()
   if g['metric']in ['Rstat','Rdyn'] and ('corresponding ranks'in text or 'ranking comparison'in text):
    self.assertEqual(task_metric_role(g),'DERIVED_RANK');found+=1
   if 'privacy safe rate'in text:
    m=inspect(g,{'matched_capabilities':['factual_accuracy','privacy','safety'],'catalog_labels':{},'label_evidence':[]},{'domains':[],'tasks':[]})
    self.assertNotIn('factual_accuracy',m['capabilities'])
  self.assertGreater(found,0)

if __name__=='__main__':unittest.main()
