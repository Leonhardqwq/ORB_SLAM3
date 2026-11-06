"""Serial native trace runs. Keep historical batches immutable; see README."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
import random
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


TERMINAL = {'completed', 'execution_error', 'start_error', 'output_error',
            'timeout', 'interrupted', 'internal_error'}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def execution_plan(protocol):
    raw = protocol['instrumentation_plan']
    defaults = dict(seed=20261029, pilot_sequence=raw['overhead_sequence'],
                    formal_frames=0, timeout_seconds=1800, pause_seconds=5)
    required = {'sequences', 'repetitions', 'overhead_sequence', 'overhead_frames',
                'overhead_pairs', 'pilot_frames', 'retain_native_scheduling', 'playback'}
    unknown = set(raw) - required - set(defaults) - {'record', 'outputs', 'topology_focus'}
    if unknown or required - set(raw):
        raise ValueError(f'Unknown or missing execution fields: {unknown}, {required - set(raw)}')
    plan = {**defaults, **{key: value for key, value in raw.items()
                          if key not in {'record', 'outputs', 'topology_focus'}}}
    if plan['retain_native_scheduling'] is not True:
        raise ValueError('This runner preserves native scheduling')
    if plan['playback'] not in ('periodic', 'periodic, original KITTI timestamps'):
        raise ValueError('This runner supports periodic KITTI playback only')
    plan['playback'] = 'periodic'
    seqs = plan['sequences']
    if not isinstance(seqs, list) or not seqs or len(set(seqs)) != len(seqs):
        raise ValueError('sequences must be a nonempty unique list')
    for seq in seqs + [plan['overhead_sequence'], plan['pilot_sequence']]:
        if not isinstance(seq, str) or seq not in [f'{n:02d}' for n in range(13)]:
            raise ValueError(f'Unsupported KITTI sequence: {seq!r}')
    for key in ('repetitions', 'overhead_frames', 'overhead_pairs', 'pilot_frames',
                'formal_frames', 'seed'):
        minimum = 0 if key in ('formal_frames', 'seed') else 1
        if type(plan[key]) is not int or plan[key] < minimum:
            raise ValueError(f'{key} must be an integer >= {minimum}')
    for key in ('timeout_seconds', 'pause_seconds'):
        value = plan[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{key} must be finite and nonnegative')
    if plan['timeout_seconds'] == 0:
        raise ValueError('timeout_seconds must be positive')
    return plan


def make_jobs(plan, phase):
    if phase == 'pilot':
        return [dict(sequence=plan['pilot_sequence'], repeat=1, trace=True,
                     frames=plan['pilot_frames'])]
    jobs = []
    if phase == 'overhead':
        for repeat in range(1, plan['overhead_pairs'] + 1):
            for enabled in ([False, True] if repeat % 2 else [True, False]):
                jobs.append(dict(sequence=plan['overhead_sequence'], repeat=repeat,
                                 trace=enabled, frames=plan['overhead_frames']))
    elif phase == 'formal':
        rng = random.Random(plan['seed'])
        for repeat in range(1, plan['repetitions'] + 1):
            seqs = list(plan['sequences'])
            rng.shuffle(seqs)
            jobs.extend(dict(sequence=seq, repeat=repeat, trace=True,
                             frames=plan['formal_frames']) for seq in seqs)
    else:
        raise ValueError(f'Unknown phase: {phase}')
    return jobs


def config_name(sequence):
    if int(sequence) <= 2:
        return 'KITTI00-02.yaml'
    return 'KITTI03.yaml' if sequence == '03' else 'KITTI04-12.yaml'


def freeze_inputs(dest, frozen):
    path = dest / 'frozen.json'
    if path.exists():
        if read(path) != frozen:
            raise RuntimeError('Changed resume inputs; use a new work directory')
    else:
        # Refuse orphaned attempts and old directories rather than adopting them.
        if dest.exists() and any(dest.iterdir()):
            raise RuntimeError(f'Nonempty batch without frozen inputs: {dest}')
        dest.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(frozen, stream, indent=2)
            stream.write('\n')


def validate_outputs(run, expected, trace):
    """Validate recording, not tracking quality or backend completion."""
    errors, frames, event_count = [], 0, 0
    try:
        with (run / 'frames.csv').open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            times = ['dataset_s', 'release_s', 'read_begin_s', 'read_end_s',
                     'track_begin_s', 'track_end_s']
            if not {'frame', *times}.issubset(reader.fieldnames or []):
                raise ValueError('missing frame/time columns')
            for number, row in enumerate(reader):
                if int(row['frame']) != number or None in row:
                    raise ValueError('invalid frame order or row width')
                values = [float(row[key]) for key in times]
                if not all(math.isfinite(value) for value in values):
                    raise ValueError('nonfinite frame timestamp')
                if values[2:] != sorted(values[2:]):
                    raise ValueError('inverted frame boundaries')
                frames += 1
        if frames != expected:
            raise ValueError(f'{frames} frames, expected {expected}')
    except (OSError, ValueError, TypeError, KeyError, csv.Error) as exc:
        errors.append(f'frames.csv: {exc}')
    try:
        meta = read(run / 'runner.json')
        required = dict(frames=expected, playback='periodic', observation='full',
                        viewer=False, backend_drained=False)
        if not isinstance(meta, dict) or any(meta.get(k) != v for k, v in required.items()):
            raise ValueError('missing or inconsistent completion metadata')
    except (OSError, ValueError, TypeError) as exc:
        errors.append(f'runner.json: {exc}')
    if trace:
        try:
            calls = {'call_begin': {}, 'call_end': {}}
            identities, epochs = 0, 0
            with (run / 'events.csv').open(encoding='utf-8', newline='') as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != ['ns', 'thread', 'event', 'id', 'aux', 'map']:
                    raise ValueError('invalid event header')
                for row in reader:
                    stamp, thread, identity, _, _ = [int(row[k]) for k in
                                                      ('ns', 'thread', 'id', 'aux', 'map')]
                    if None in row or stamp <= 0 or thread <= 0 or not row['event']:
                        raise ValueError('invalid event row')
                    kind = row['event']
                    event_count += 1
                    if kind in calls:
                        if identity in calls[kind]:
                            raise ValueError('duplicate call boundary')
                        calls[kind][identity] = stamp
                    identities += kind == 'frame_identity'
                    epochs += kind == 'epoch'
            expected_ids = set(range(expected))
            if epochs != 1 or identities != expected:
                raise ValueError('missing epoch or frame identity records')
            if any(set(side) != expected_ids for side in calls.values()):
                raise ValueError('missing or extra call boundaries')
            if any(calls['call_begin'][i] > calls['call_end'][i] for i in expected_ids):
                raise ValueError('inverted call boundaries')
            # Backend spans may remain open at native shutdown; keep them as censored.
        except (OSError, ValueError, TypeError, KeyError, csv.Error) as exc:
            errors.append(f'events.csv: {exc}')
    return dict(frames=frames, event_rows=event_count, output_errors=errors)


def stop_process(proc):
    if proc.poll() is not None:
        return
    try:
        if os.name == 'posix':
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if os.name == 'posix':
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
        proc.wait()


def run_attempt(run, job, command, expected, timeout):
    run.mkdir()  # Never overwrite a previous or interrupted attempt.
    result = {**job, 'status': 'running', 'command': command, 'expected_frames': expected,
              'started_utc': utc_now()}
    write(run / 'result.json', result)
    env = os.environ.copy()
    env.pop('ORB_NATIVE_TRACE', None)
    if job['trace']:
        env['ORB_NATIVE_TRACE'] = str(run / 'events.csv')
    proc, code, status = None, None, 'execution_error'
    start = time.monotonic()
    try:
        with (run / 'process.log').open('w', encoding='utf-8') as log, \
                (run / 'resources.csv').open('w', encoding='utf-8', newline='') as resource:
            writer = csv.writer(resource)
            writer.writerow(['monotonic_ns', 'rss_kib', 'threads'])
            proc = subprocess.Popen(command, cwd=run, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            while proc.poll() is None:
                try:
                    lines = Path(f'/proc/{proc.pid}/status').read_text().splitlines()
                    rss = next((int(x.split()[1]) for x in lines if x.startswith('VmRSS:')), 0)
                    threads = next((int(x.split()[1]) for x in lines if x.startswith('Threads:')), 0)
                    writer.writerow([time.monotonic_ns(), rss, threads])
                except FileNotFoundError:
                    pass
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    status = 'timeout'
                    stop_process(proc)
                    break
                time.sleep(min(1, remaining))
            code = proc.wait()
            if status != 'timeout':
                status = 'completed' if code == 0 else 'execution_error'
    except KeyboardInterrupt:
        status = 'interrupted'
    except Exception as exc:
        status = 'start_error' if proc is None else 'internal_error'
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if proc is not None:
            stop_process(proc)
            code = proc.returncode
        validation = validate_outputs(run, expected, job['trace'])
        if status == 'completed' and validation['output_errors']:
            status = 'output_error'
        result.update(validation, status=status, exit_code=code,
                      wall_seconds=time.monotonic() - start, finished_utc=utc_now())
        write(run / 'result.json', result)
    return result


def run_batch(root, work, phase, protocol):
    root, work = root.resolve(), work.resolve()
    plan = execution_plan(protocol)
    jobs = make_jobs(plan, phase)
    source, binary = work / 'source-v2', work / 'observer/native_kitti'
    data = root / 'data/kitti/sequences'
    sequences = sorted({job['sequence'] for job in jobs})
    inputs = [binary, source / 'lib/libORB_SLAM3.so', source / 'Vocabulary/ORBvoc.txt',
              Path(__file__).resolve()]
    inputs += [source / 'Examples/Stereo' / config_name(seq) for seq in sequences]
    inputs += [data / seq / 'times.txt' for seq in sequences]
    expected = {}
    for seq in sequences:
        stamps = [float(t) for t in (data / seq / 'times.txt').read_text().split()]
        if not stamps or not all(math.isfinite(t) for t in stamps) or any(
                a >= b for a, b in zip(stamps, stamps[1:])):
            raise ValueError(f'Invalid KITTI timestamps: {seq}')
        expected[seq] = len(stamps)
    for job in jobs:
        if job['frames'] > expected[job['sequence']]:
            raise ValueError(f'Requested frame count exceeds sequence length: {job}')
    frozen = dict(schema=2, protocol=protocol, effective_plan=plan, jobs=jobs,
                  root=str(root), work=str(work), input_sha256={str(p): sha(p) for p in inputs})
    dest = work / 'runs' / phase
    freeze_inputs(dest, frozen)
    results = []
    try:
        for number, job in enumerate(jobs, 1):
            run = dest / f'{number:02d}-s{job["sequence"]}-r{job["repeat"]}-trace{int(job["trace"])}'
            if (run / 'result.json').exists():
                result = read(run / 'result.json')
                if result.get('status') not in TERMINAL:
                    raise RuntimeError(f'Inspect interrupted attempt: {run}')
            else:
                command = [str(binary), str(source / 'Vocabulary/ORBvoc.txt'),
                           str(source / 'Examples/Stereo' / config_name(job['sequence'])),
                           str(data / job['sequence']), 'periodic', 'full', str(job['frames']), str(run)]
                print('start', run.name, flush=True)
                result = run_attempt(run, job, command, job['frames'] or expected[job['sequence']],
                                     plan['timeout_seconds'])
                print('finish', run.name, result['status'], result['frames'], flush=True)
            results.append(result)
            if result['status'] == 'interrupted':
                raise KeyboardInterrupt
            if number < len(jobs):
                time.sleep(plan['pause_seconds'])
    finally:
        all_completed = len(results) == len(jobs) and all(r['status'] == 'completed' for r in results)
        write(dest / 'finished.json', dict(planned_attempts=len(jobs), attempts=len(results),
              statuses=dict(Counter(r['status'] for r in results)), all_completed=all_completed,
              finished_utc=utc_now()))
    return 0 if all_completed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='native root containing data/kitti')
    parser.add_argument('--work', type=Path, required=True, help='new trace directory with source-v2 and observer')
    parser.add_argument('--phase', choices=['pilot', 'overhead', 'formal'], required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('Run native KITTI batches in Linux/WSL; portable tests do not run SLAM')
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        return run_batch(args.root, args.work, args.phase, read(args.protocol))
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
