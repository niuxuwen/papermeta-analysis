import unittest
from metric_semantics import check_direction,audit_directions
from weighted_bt import pair_records

class DirectionTests(unittest.TestCase):
    def test_no_concern_is_not_low_is_good(self):
        self.assertEqual(check_direction(dict(metric='No-concern replies (%)',direction='lower'))['status'],'CONFLICT')
    def test_caption_cannot_override_column(self):
        g=dict(metric='Accuracy',direction='higher',metric_role_context='Loss and accuracy; lower is better for loss')
        self.assertEqual(check_direction(g)['status'],'CONSISTENT')
    def test_distribution_needs_segment_identity(self):
        g=dict(metric='Severity of replies (%)',direction='lower',metric_role_context='no concern, minor, major and critical')
        self.assertEqual(check_direction(g)['status'],'REVIEW_REQUIRED')
    def test_conflicting_arrow_is_not_silently_corrected(self):
        self.assertEqual(check_direction(dict(metric='Accuracy ↓',direction='lower'))['status'],'REVIEW_REQUIRED')
    def test_unknown_metric_not_arbitrarily_rejected(self):
        self.assertEqual(check_direction(dict(metric='NovelUtility',direction='higher'))['status'],'UNVERIFIED')
    def test_comparison_builder_cannot_bypass_guard(self):
        g=dict(group_id='g',paper_id='p',benchmark_id='b',metric='No-concern replies (%)',direction='lower',scores=[dict(model_canonical='A',value_numeric=11),dict(model_canonical='B',value_numeric=69)])
        edges,why=pair_records([g]);self.assertFalse(edges);self.assertEqual(why['metric_direction_requires_review'],1)
        g['direction']='higher';edges,_=pair_records([g]);self.assertEqual(edges[0]['y'],0)
    def test_group_only_hold_preserves_values(self):
        g=dict(group_id='g',paper_id='p',metric='Collisions',direction='higher',scores=[1,2])
        events=audit_directions([g]);self.assertEqual(len(events),1);self.assertEqual(g['scores'],[1,2]);self.assertEqual(g['direction'],'higher')

if __name__=='__main__':unittest.main()
