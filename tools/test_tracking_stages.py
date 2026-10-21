import unittest
from check_tracking_stages import check_rows,STAGES
class TrackingChecks(unittest.TestCase):
    def fixture(self):
        e=dict(round=0,k=0,release_ns=10,aT_ns=20,eT_ns=80,aB_ns=90,eB_ns=100)
        r=dict(round=0,k=0,context_begin_ns=11,context_end_ns=19,read_begin_ns=81,read_end_ns=89,
               map_id=0,map_points=0,map_keyframes=0,before_keypoints=0,before_point_slots=0,before_nonnull_points=0,pending_reset=0)
        for s in STAGES:
            for suffix in ['_ns','_begin_ns','_end_ns','_calls']:r[s+suffix]=0
        r.update(extraction_ns=30,extraction_begin_ns=25,extraction_end_ns=55,extraction_calls=1)
        return e,r
    def test_valid_early_exit(self):
        e,r=self.fixture();self.assertEqual(check_rows([e],[r]),[])
    def test_overlap_rejected(self):
        e,r=self.fixture();r.update(stereo_match_ns=20,stereo_match_begin_ns=50,stereo_match_end_ns=70,stereo_match_calls=1)
        self.assertTrue(any('overlap' in s for s in check_rows([e],[r])))
    def test_outside_and_stale(self):
        e,r=self.fixture();r['context_end_ns']=21;r['keyframe_ns']=1
        self.assertEqual(len(check_rows([e],[r])),2)
    def test_missing_rows(self):
        e,r=self.fixture();self.assertTrue(check_rows([e],[]))
if __name__=='__main__':unittest.main()
