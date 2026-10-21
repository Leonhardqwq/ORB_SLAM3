import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from replay_resources import parse_cpus, launch_command, Recorder


class ResourcePolicyTests(unittest.TestCase):
    def test_native_command_unmodified(self):
        command = ['native-binary', 'configuration']
        self.assertIs(launch_command(command, None), command)

    def test_reject_unavailable_or_malformed_cpus(self):
        for value in ['', '1-3', '0,0', '0,9', '-1', '0;echo']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_cpus(value, [0, 1, 2])

    def test_affinity_inherited_by_real_threads(self):
        cpus = tuple(sorted(os.sched_getaffinity(0))[:2])
        code = ('import json,os,threading,time; masks=[]; '
                'ts=[threading.Thread(target=lambda:masks.append(sorted(os.sched_getaffinity(0)))) for _ in range(3)]; '
                '[t.start() for t in ts]; [t.join() for t in ts]; '
                'print(json.dumps(masks),flush=True); time.sleep(.15)')
        result = subprocess.run(launch_command([sys.executable, '-c', code], cpus),
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [list(cpus)] * 3)

    def test_counters_record_real_process_and_requested_affinity(self):
        cpus = tuple(sorted(os.sched_getaffinity(0))[:2])
        with tempfile.TemporaryDirectory() as directory:
            child = subprocess.Popen(launch_command([sys.executable, '-c', 'import time; time.sleep(.2)'], cpus))
            record = Recorder(Path(directory)/'resources.csv', cpus)
            try:
                time.sleep(.03)
                record.observe(child.pid, Path(f'/proc/{child.pid}/status').read_text())
                time.sleep(.03)
                record.observe(child.pid, Path(f'/proc/{child.pid}/status').read_text())
            finally:
                child.wait(timeout=5)
            result = record.finish()
            self.assertEqual(result['errors'], [])
            self.assertEqual(result['samples'], 2)
            self.assertGreater(record.rows[1]['monotonic_ns'], record.rows[0]['monotonic_ns'])
            self.assertGreaterEqual(record.rows[1]['leader_cpu_ticks'], record.rows[0]['leader_cpu_ticks'])


if __name__ == '__main__':
    unittest.main()
