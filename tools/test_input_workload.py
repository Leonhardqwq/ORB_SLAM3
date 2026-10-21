import copy,unittest
from check_input_workload import check_rows
class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.events=[dict(k=0,release_ns=100,aT_ns=120,eT_ns=200,aB_ns=220,eB_ns=300)]
        self.rows=[dict(k=0,probe_before_begin_ns=105,probe_before_end_ns=115,probe_after_begin_ns=205,probe_after_end_ns=215,
            process_cpu_before_T_ns=1000,process_cpu_after_T_ns=1050,coordinator_voluntary_before=0,coordinator_voluntary_after=1,
            coordinator_involuntary_before=0,coordinator_involuntary_after=0,before_keypoints=10,before_point_slots=10,before_nonnull_points=3,
            after_keypoints=10,after_point_slots=10,after_nonnull_points=5)]
    def test_legal_costs_are_inside_gaps(self):self.assertEqual(check_rows(self.events,self.rows),[])
    def test_missing_and_wrong_round(self):
        self.assertTrue(check_rows(self.events,[]));self.rows[0]['k']=1;self.assertTrue(check_rows(self.events,self.rows))
    def test_probe_outside_task_gap_rejected(self):
        self.rows[0]['probe_before_end_ns']=121;self.assertTrue(check_rows(self.events,self.rows))
    def test_negative_cpu_or_invalid_count_rejected(self):
        self.rows[0]['process_cpu_after_T_ns']=900;self.assertTrue(check_rows(self.events,self.rows))
        self.rows[0]['process_cpu_after_T_ns']=1100;self.rows[0]['after_nonnull_points']=11;self.assertTrue(check_rows(self.events,self.rows))
if __name__=='__main__':unittest.main()
