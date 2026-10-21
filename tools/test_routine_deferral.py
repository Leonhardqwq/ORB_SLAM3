import csv,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from check_routine_deferral import check
class RoutineTests(unittest.TestCase):
    def test_guard_effect_and_default_isolation(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            trace=dict(round=1,keyframe_flags=2|64|128|512,work_mode=1,match_inliers=75)
            event=dict(round=1,state=2,keyframes=0)
            def run(t=None,e=None,enabled=True):
                for name,row in [('replay-tracking.csv',trace|dict(t or {})),('replay-events.csv',event|dict(e or {}))]:
                    with (root/name).open('w',newline='') as f:
                        w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
                return check(root,enabled)
            self.assertEqual(run(),[])
            self.assertIn('routine_deferral_leaked',run(enabled=False))
            for t in [dict(work_mode=0),dict(match_inliers=74)]+[dict(keyframe_flags=trace['keyframe_flags']|b) for b in [1,4,32,256]]:
                with self.subTest(t=t):self.assertIn('routine_deferral_guard',run(t))
            self.assertIn('routine_deferral_effect',run(e=dict(keyframes=1)))
            self.assertIn('routine_deferral_effect',run(e=dict(state=3)))
            self.assertEqual(run(t=dict(keyframe_flags=0),e=dict(keyframes=1),enabled=False),[])
if __name__=='__main__':unittest.main()
