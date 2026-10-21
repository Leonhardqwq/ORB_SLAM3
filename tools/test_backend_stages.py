import unittest,csv
from pathlib import Path
from tempfile import TemporaryDirectory
from check_backend_stages import check,STAGES
class BackendTests(unittest.TestCase):
    def test_boundaries_stale_records_and_caps(self):
        with TemporaryDirectory() as d:
            root=Path(d);event={'round':1,'k':0,'aB_ns':100,'eB_ns':300}
            row={'round':1,'k':0,'ba_calls':1,'ba_keyframes_max':8,'ba_points_max':2400,'ba_edges_max':9000}
            for stage in STAGES:
                for suffix in ['_ns','_begin_ns','_end_ns','_calls']:row[stage+suffix]=0
            row.update(local_ba_ns=100,local_ba_begin_ns=120,local_ba_end_ns=220,local_ba_calls=1,
                       loop_ns=20,loop_begin_ns=230,loop_end_ns=250,loop_calls=1)
            def save(name,x):
                with (root/name).open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(x));w.writeheader();w.writerow(x)
            save('replay-events.csv',event)
            def errors():save('replay-backend-stages.csv',row);return check(root,8,2400)
            self.assertEqual(errors(),[])
            row['ba_points_max']=2401;self.assertIn('backend_point_cap:0',errors());row['ba_points_max']=2400
            row['insert_ns']=1;self.assertIn('stale_backend_stage:0:insert',errors());row['insert_ns']=0
            row['loop_begin_ns']=210;row['loop_end_ns']=230
            self.assertIn('backend_overlap:0',errors())
            row['loop_begin_ns']=290;row['loop_end_ns']=310
            self.assertIn('backend_stage_boundary:0:loop',errors())
    def test_global_ba_counts_time_and_missing_evidence(self):
        with TemporaryDirectory() as d:
            root=Path(d);event={'round':1,'k':0,'aB_ns':100,'eB_ns':300}
            base={'round':1,'k':0,'ba_calls':0,'ba_keyframes_max':0,'ba_points_max':0,
                  'gba_calls':1,'gba_requested_max':3,'gba_actual_max':2,
                  'gba_iteration_errors':0,'gba_optimization_ns':20}
            for stage in STAGES:
                for suffix in ['_ns','_begin_ns','_end_ns','_calls']:base[stage+suffix]=0
            base.update(loop_ns=100,loop_begin_ns=120,loop_end_ns=220,loop_calls=1)
            def save(name,row):
                with (root/name).open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
            save('replay-events.csv',event)
            def errors(changes=None,missing=None):
                row=base.copy();row.update(changes or {})
                if missing:row.pop(missing)
                save('replay-backend-stages.csv',row)
                return check(root,global_iterations=3)
            self.assertEqual(errors(),[])
            for change,expected in [
                ({'gba_actual_max':4},'global_ba_iterations:0'),
                ({'gba_actual_max':-1},'global_ba_iterations:0'),
                ({'gba_iteration_errors':1},'global_ba_iterations:0'),
                ({'gba_requested_max':2},'global_ba_requested:0'),
                ({'gba_optimization_ns':101},'global_ba_time:0'),
                ({'gba_optimization_ns':-1},'global_ba_time:0'),
                ({'gba_calls':0},'global_ba_stale:0')]:
                with self.subTest(change=change):self.assertIn(expected,errors(change))
            self.assertIn('global_ba_iterations:0',errors(missing='gba_actual_max'))
            self.assertEqual(errors({'gba_calls':0,'gba_requested_max':0,
                                    'gba_actual_max':0,'gba_optimization_ns':0}),[])
if __name__=='__main__':unittest.main()
