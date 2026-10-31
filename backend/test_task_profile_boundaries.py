from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,'D:/FDU/benchmark-radar')
import recent_benchmarks
recent_benchmarks.__path__.insert(0,str(Path(__file__).parent/'task_rules'))
from recent_benchmarks.interactive_profile import CompactProfileClient
from recent_benchmarks.task_labels import builtin_profile,build_task_profile,_constraint_is_literal

class Generated:
    def __init__(self,data):self.data=data
    def complete_json(self,**request):
        result=request['validator'](deepcopy(self.data))
        return request['validator'](deepcopy(result))

def output():
    p=builtin_profile('medical-literature-review')
    return {**{k:p[k]for k in ('domains','tasks','capabilities','constraints')},'constraint_evidence':{}}

class ProfileBoundaryTests(unittest.TestCase):
    def test_recording_words_are_literal_media_evidence(self):
        for word in ['会议录音','会议录像','软件操作录屏','meeting recording']:
            self.assertTrue(_constraint_is_literal('modality','multimodal',word))
    def test_translation_does_not_acquire_an_invented_text_only_constraint(self):
        raw=output();raw['constraints'].update(modality='text',language='zh');raw['constraint_evidence']={'language':'把英文摘要翻译成中文'}
        before=deepcopy(raw)
        p=build_task_profile(CompactProfileClient(Generated(raw)),'把英文摘要翻译成中文，保留原文含义。')
        self.assertEqual(p['constraints']['modality'],'any');self.assertEqual(p['constraints']['language'],'zh');self.assertEqual(raw,before)
    def test_actual_text_only_requirement_is_retained(self):
        raw=output();raw['constraints']['modality']='text';raw['constraint_evidence']={'modality':'仅文本'}
        p=build_task_profile(CompactProfileClient(Generated(raw)),'仅文本输入，整理医学文献。')
        self.assertEqual(p['constraints']['modality'],'text')
    def test_audio_input_cannot_be_silently_replaced_by_text_only(self):
        raw=output();raw['constraints']['modality']='text'
        p=build_task_profile(CompactProfileClient(Generated(raw)),'听会议录音，整理讨论要点。')
        self.assertEqual(p['constraints']['modality'],'audio')
    def test_supported_recording_constraint_passes_without_a_second_model_call(self):
        raw=output();raw['constraints']['modality']='multimodal';raw['constraint_evidence']={'modality':'听会议录音'}
        p=build_task_profile(CompactProfileClient(Generated(raw)),'听会议录音，整理讨论要点。')
        self.assertEqual(p['constraints']['modality'],'audio')
    def test_tool_retrieval_and_invalid_capability_guards_are_preserved(self):
        raw=output();raw['constraints']['knowledge_access']='retrieval';raw['constraint_evidence']={'knowledge_access':'不允许联网'}
        p=build_task_profile(CompactProfileClient(Generated(raw)),'不允许联网，整理医学文献。')
        self.assertEqual(p['constraints']['knowledge_access'],'closed_book')
        raw=output();raw['capabilities'][0]['id']='imaginary'
        with self.assertRaises(ValueError):build_task_profile(CompactProfileClient(Generated(raw)),'整理医学文献。')

if __name__=='__main__':unittest.main()
