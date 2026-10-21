import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from check_backend_stages import check,STAGES


class ObserverBudgetAuditTests(unittest.TestCase):
    def test_missing_counts_caps_anchor_and_edge_failures(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            event=dict(round=0,k=0,aB_ns=0,eB_ns=100)
            row=dict(round=0,k=0,ba_calls=1,ba_keyframes_max=4,ba_points_max=1200,
                ba_edges_max=9000,ba_fixed_keyframes_max=4,ba_fixed_candidates_max=40,
                ba_dropped_points_max=1,ba_anchor_rejects=0)
            for stage in STAGES:
                for suffix in ['_ns','_begin_ns','_end_ns','_calls']:row[stage+suffix]=0
            row.update(local_ba_ns=20,local_ba_begin_ns=10,local_ba_end_ns=30,local_ba_calls=1,
                       loop_ns=20,loop_begin_ns=40,loop_end_ns=60,loop_calls=1)
            def write(name,record):
                with (root/name).open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=list(record));writer.writeheader();writer.writerow(record)
            write('replay-events.csv',event)
            def errors(change=None,missing=None):
                values=row|dict(change or {})
                if missing:values.pop(missing)
                write('replay-backend-stages.csv',values)
                return check(root,4,1200,fixed_keyframes=4)
            self.assertEqual(errors(),[])
            for change,expected in [
                ({'ba_fixed_keyframes_max':5},'backend_fixed_observer_cap:0'),
                ({'ba_fixed_candidates_max':2},'backend_fixed_observer_cap:0'),
                ({'ba_edges_max':19201},'backend_edge_cap:0'),
                ({'ba_dropped_points_max':1201},'backend_point_constraints:0'),
                ({'ba_anchor_rejects':1},'backend_anchor_guard:0'),
                ({'ba_anchor_rejects':2},'backend_anchor_guard:0')]:
                with self.subTest(change=change):self.assertIn(expected,errors(change))
            self.assertIn('backend_fixed_observer_cap:0',errors(missing='ba_fixed_keyframes_max'))
            self.assertEqual(errors(dict(ba_calls=0,ba_keyframes_max=0,ba_points_max=0,ba_edges_max=0,
                ba_fixed_keyframes_max=0,ba_fixed_candidates_max=0,ba_dropped_points_max=0,ba_anchor_rejects=1)),[])


if __name__=='__main__':unittest.main()
