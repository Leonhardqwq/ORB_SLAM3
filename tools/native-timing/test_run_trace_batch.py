"""Small runner checks using disposable files and Python processes, never SLAM."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('trace_runner', Path(__file__).with_name('run_trace_batch.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

PROTOCOL = {
    'batch': 'test-only',
    'instrumentation_plan': {
        'retain_native_scheduling': True, 'playback': 'periodic, original KITTI timestamps',
        'sequences': ['03', '07'], 'repetitions': 2, 'overhead_sequence': '07',
        'overhead_frames': 2, 'overhead_pairs': 2, 'pilot_frames': 2,
        'timeout_seconds': 10, 'pause_seconds': 0,
    },
}
JOB = dict(sequence='07', repeat=1, trace=True, frames=2)
CHILD = r"""
import csv, json, os, sys, time
from pathlib import Path
mode = sys.argv[1]
if mode == 'hang':
    time.sleep(60)
if mode != 'missing_frames':
    with open('frames.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['frame', 'dataset_s', 'release_s', 'read_begin_s', 'read_end_s',
                         'track_begin_s', 'track_end_s', 'state'])
        writer.writerow([0, 0, 0, .001, .002, .003, .004, 1])
        writer.writerow([1, .1, .1, .101, .102, .103, .104, 3])
if mode != 'missing_meta':
    Path('runner.json').write_text(json.dumps(dict(
        frames=1 if mode == 'bad_meta' else 2, playback='periodic',
        observation='full', viewer=False, backend_drained=False)))
if os.environ.get('ORB_NATIVE_TRACE') and mode != 'missing_events':
    Path(os.environ['ORB_NATIVE_TRACE']).write_text(
        'ns,thread,event,id,aux,map\n'
        '100,1,epoch,-1,-1,-1\n'
        '110,1,call_begin,0,-1,-1\n'
        '115,1,frame_identity,8,-1,-1\n'
        '120,1,call_end,0,-1,-1\n'
        '125,2,local_mapping_begin,4,8,-1\n'
        '130,1,call_begin,1,-1,-1\n'
        '135,1,frame_identity,9,-1,-1\n'
        '140,1,call_end,1,-1,-1\n')
if mode == 'nonzero':
    sys.exit(7)
"""


class TraceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orb-trace-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protocol = copy.deepcopy(PROTOCOL)

    def attempt(self, mode='success', trace=True, name='attempt', timeout=10):
        run = self.root / name
        job = {**JOB, 'trace': trace}
        result = runner.run_attempt(run, job, [sys.executable, '-B', '-c', CHILD, mode], 2, timeout)
        self.assertEqual(result, runner.read(run / 'result.json'))
        self.assertIn('finished_utc', result)
        self.assertNotEqual(result['status'], 'running')
        return run, result

    def fixture(self):
        run = self.root / 'fixture'
        run.mkdir()
        subprocess.run([sys.executable, '-B', '-c', CHILD, 'success'], cwd=run,
                       env={**os.environ, 'ORB_NATIVE_TRACE': str(run / 'events.csv')}, check=True)
        return run

    def test_protocol_controls_jobs_and_order(self):
        plan = runner.execution_plan(self.protocol)
        jobs = runner.make_jobs(plan, 'formal')
        self.assertEqual(len(jobs), 4)
        self.assertEqual({j['sequence'] for j in jobs}, {'03', '07'})
        self.assertEqual([j['repeat'] for j in jobs], [1, 1, 2, 2])
        self.assertEqual(jobs, runner.make_jobs(plan, 'formal'))
        self.assertEqual([j['trace'] for j in runner.make_jobs(plan, 'overhead')],
                         [False, True, True, False])
        plan['pilot_sequence'], plan['pilot_frames'] = '03', 1
        self.assertEqual(runner.make_jobs(plan, 'pilot')[0]['sequence'], '03')
        self.assertEqual(runner.make_jobs(plan, 'pilot')[0]['frames'], 1)
        self.assertEqual(runner.config_name('03'), 'KITTI03.yaml')
        self.assertEqual(runner.config_name('00'), 'KITTI00-02.yaml')

    def test_invalid_protocol_is_rejected(self):
        for key, value in [('sequences', ['../07']), ('sequences', ['07', '07']),
                           ('repetitions', True), ('pilot_frames', 0),
                           ('timeout_seconds', 0), ('pause_seconds', float('nan')),
                           ('retain_native_scheduling', False), ('playback', 'upstream'),
                           ('repetitons', 8)]:
            with self.subTest(key=key, value=value):
                protocol = copy.deepcopy(PROTOCOL)
                protocol['instrumentation_plan'][key] = value
                with self.assertRaises(ValueError):
                    runner.execution_plan(protocol)

    def test_freeze_rejects_changes_and_old_batches(self):
        dest = self.root / 'batch'
        runner.freeze_inputs(dest, {'schema': 1})
        before = (dest / 'frozen.json').read_bytes()
        with self.assertRaises(RuntimeError):
            runner.freeze_inputs(dest, {'schema': 2})
        self.assertEqual(before, (dest / 'frozen.json').read_bytes())
        orphan = self.root / 'orphan'
        orphan.mkdir()
        (orphan / 'result.json').write_text('{}')
        with self.assertRaises(RuntimeError):
            runner.freeze_inputs(orphan, {'schema': 2})

    def test_complete_output_accepts_open_backend_and_tracking_loss(self):
        _, result = self.attempt()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['frames'], 2)
        self.assertEqual(result['event_rows'], 8)
        self.assertEqual(result['output_errors'], [])

    def test_missing_or_inconsistent_outputs_cannot_pass(self):
        for mode in ('missing_frames', 'missing_meta', 'bad_meta', 'missing_events'):
            with self.subTest(mode=mode):
                _, result = self.attempt(mode, name=mode)
                self.assertEqual(result['exit_code'], 0)
                self.assertEqual(result['status'], 'output_error')
                self.assertTrue(result['output_errors'])

    def test_trace_disabled_clears_inherited_environment(self):
        with patch.dict(os.environ, {'ORB_NATIVE_TRACE': str(self.root / 'unwanted.csv')}):
            run, result = self.attempt(trace=False)
        self.assertEqual(result['status'], 'completed')
        self.assertFalse((run / 'events.csv').exists())
        self.assertFalse((self.root / 'unwanted.csv').exists())

    def test_nonzero_exit_remains_failure_even_with_complete_outputs(self):
        _, result = self.attempt('nonzero')
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['status'], 'execution_error')
        self.assertEqual(result['output_errors'], [])

    def test_start_failure_is_finalized(self):
        run = self.root / 'missing-executable'
        result = runner.run_attempt(run, JOB, [str(self.root / 'does-not-exist')], 2, 1)
        self.assertEqual(result['status'], 'start_error')
        self.assertEqual(result, runner.read(run / 'result.json'))
        self.assertIsNone(result['exit_code'])

    def test_timeout_stops_and_reaps_child(self):
        real_popen = subprocess.Popen
        processes = []
        def capture(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(runner.subprocess, 'Popen', side_effect=capture):
            _, result = self.attempt('hang', timeout=.1)
        self.assertEqual(result['status'], 'timeout')
        self.assertIsNotNone(processes[0].poll())
        self.assertLess(result['wall_seconds'], 7)

    @unittest.skipUnless(os.name == 'posix', 'POSIX process-group kill escalation')
    def test_timeout_escalates_if_sigterm_ignored(self):
        command = [sys.executable, '-B', '-c',
                   'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']
        result = runner.run_attempt(self.root / 'ignores-term', JOB, command, 2, .5)
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['exit_code'], -9)

    def test_interruption_is_finalized_and_requests_cleanup(self):
        process = Mock()
        process.poll.side_effect = KeyboardInterrupt
        process.returncode = -15
        with patch.object(runner.subprocess, 'Popen', return_value=process), \
                patch.object(runner, 'stop_process') as stop:
            result = runner.run_attempt(self.root / 'interrupted', JOB, ['fake'], 2, 1)
        self.assertEqual(result['status'], 'interrupted')
        stop.assert_called_once_with(process)
        self.assertEqual(result, runner.read(self.root / 'interrupted/result.json'))

    def test_existing_attempt_is_not_overwritten(self):
        run = self.root / 'existing'
        run.mkdir()
        (run / 'result.json').write_text('{"status":"running"}')
        with self.assertRaises(FileExistsError):
            runner.run_attempt(run, JOB, ['fake'], 2, 1)
        self.assertEqual(runner.read(run / 'result.json'), {'status': 'running'})

    def test_truncated_duplicate_and_malformed_events_fail(self):
        run = self.fixture()
        path = run / 'events.csv'
        original = path.read_text()
        invalid = [original.rsplit('140,', 1)[0], original + '140,1,call_end,1,-1,-1\n',
                   'ns,thread,event,id,aux,map\n', original + 'bad,row\n',
                   original.replace('140,1,call_end', '129,1,call_end')]
        for content in invalid:
            with self.subTest(content=content[-50:]):
                path.write_text(content)
                self.assertTrue(runner.validate_outputs(run, 2, True)['output_errors'])

    def test_invalid_frame_boundaries_fail(self):
        run = self.fixture()
        path = run / 'frames.csv'
        content = path.read_text().replace('0.103,0.104', '0.103,0.100')
        path.write_text(content)
        self.assertTrue(runner.validate_outputs(run, 2, True)['output_errors'])

    def batch_fixture(self):
        work = self.root / 'new-work'
        for relative in ['source-v2/lib/libORB_SLAM3.so', 'source-v2/Vocabulary/ORBvoc.txt',
                         'source-v2/Examples/Stereo/KITTI04-12.yaml', 'observer/native_kitti']:
            path = work / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('test fixture only')
        times = self.root / 'data/kitti/sequences/07/times.txt'
        times.parent.mkdir(parents=True)
        times.write_text('0.0\n0.1\n')
        return work

    def test_batch_failure_summary_resume_and_frozen_input(self):
        work = self.batch_fixture()
        real_attempt = runner.run_attempt
        def fake_attempt(run, job, command, expected, timeout):
            self.assertTrue(all(Path(command[i]).is_absolute() for i in (0, 1, 2, 3, 7)))
            return real_attempt(run, job, [sys.executable, '-B', '-c', CHILD, 'missing_events'],
                                expected, timeout)
        with patch.object(runner, 'run_attempt', side_effect=fake_attempt) as execute:
            self.assertEqual(runner.run_batch(self.root, work, 'pilot', self.protocol), 1)
            execute.assert_called_once()
        dest = work / 'runs/pilot'
        summary = runner.read(dest / 'finished.json')
        self.assertFalse(summary['all_completed'])
        self.assertEqual(summary['statuses'], {'output_error': 1})
        result = next(dest.glob('*/result.json'))
        before = result.read_bytes()
        with patch.object(runner, 'run_attempt') as execute:
            self.assertEqual(runner.run_batch(self.root, work, 'pilot', self.protocol), 1)
            execute.assert_not_called()
        self.assertEqual(result.read_bytes(), before)
        (work / 'source-v2/Examples/Stereo/KITTI04-12.yaml').write_text('changed')
        with self.assertRaises(RuntimeError):
            runner.run_batch(self.root, work, 'pilot', self.protocol)
        self.assertEqual(result.read_bytes(), before)

    def test_batch_success_summary(self):
        work = self.batch_fixture()
        real_attempt = runner.run_attempt
        def fake_attempt(run, job, command, expected, timeout):
            return real_attempt(run, job, [sys.executable, '-B', '-c', CHILD, 'success'],
                                expected, timeout)
        with patch.object(runner, 'run_attempt', side_effect=fake_attempt):
            self.assertEqual(runner.run_batch(self.root, work, 'pilot', self.protocol), 0)
        self.assertTrue(runner.read(work / 'runs/pilot/finished.json')['all_completed'])


if __name__ == '__main__':
    unittest.main()
