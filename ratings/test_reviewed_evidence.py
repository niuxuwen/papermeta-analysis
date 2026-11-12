from copy import deepcopy
import unittest
from reviewed_evidence import merge, signature
from source_quality import attach_provenance, filter_board_records
from weighted_bt import pair_records

def group(gid, value=8):
    return dict(group_id=gid,paper_id='p',table_id='t',benchmark_id='b',metric='accuracy',model_setting='',direction='higher',
                scores=[dict(model_canonical=n,value_numeric=v,observation_ids=[gid+n],task_source_records=[dict(source_row=i,source_column=1)]) for i,(n,v) in enumerate([('A',value),('B',3)])])

class ReviewedEvidenceTests(unittest.TestCase):
    def fixture(self, live=()):
        data=dict(snapshot_id='live',window=dict(start='2026-10-01T00:00:00Z',end='2026-11-12T00:00:00Z'),index=dict(groups=list(live)))
        pack=dict(version='test',reviewed_at='2026-11-11',attested_verified_papers=1,groups=[group('review')],papers={'p':dict(arxiv_id='2610.00001',paper_first_published='2026-10-10T00:00:00Z')},classifications={})
        return data,pack

    def test_addition_preserves_source_and_is_idempotent(self):
        data,pack=self.fixture(); before=deepcopy(data)
        out,papers,audit=merge(data,{},pack,{})
        self.assertEqual(data,before);self.assertEqual(audit['added_groups'],1)
        again,_,audit2=merge(out,papers,pack,{})
        self.assertEqual(len(again['index']['groups']),1);self.assertEqual(audit2['added_groups'],0)

    def test_existing_cells_do_not_double_weight(self):
        data,pack=self.fixture([group('service')]);out,_,_=merge(data,{},pack,{})
        groups=out['index']['groups'];edges,_=pair_records(groups)
        kept,audit=filter_board_records(attach_provenance(edges,groups))
        self.assertEqual(len(kept),1);self.assertEqual(len(audit),1)

    def test_changed_live_cell_wins(self):
        data,pack=self.fixture([group('service',9)]);out,_,audit=merge(data,{},pack,{})
        self.assertEqual(len(out['index']['groups']),1)
        self.assertEqual(audit['event_counts']['changed_service_cell_requires_review'],1)

    def test_window_and_classification_are_source_bound(self):
        data,pack=self.fixture();pack['classifications']['review']=dict(source_signature=signature(group('review')),categories=['Science'])
        out,_,_=merge(data,{},pack,{})
        self.assertEqual(out['index']['groups'][0]['reviewed_categories'],['Science'])
        pack['groups'][0]['scores'][0]['value_numeric']=7
        out,_,_=merge(data,{},pack,{})
        self.assertNotIn('reviewed_categories',out['index']['groups'][0])
        pack['papers']['p']['paper_first_published']='2026-09-01T00:00:00Z'
        out,_,audit=merge(data,{},pack,{})
        self.assertEqual(out['index']['groups'],[])
        self.assertEqual(audit['event_counts']['outside_current_publication_window'],1)

if __name__=='__main__':unittest.main()
