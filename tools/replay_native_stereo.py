"""Replay the unchanged native stereo example under Xvfb (environment smoke only)."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--work', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--timeout', type=int, default=900)
a = p.parse_args()
work = a.work.resolve()
src = work / 'source'
data = work / 'data/V1_01_easy'
stamp = src / 'Examples/Stereo/EuRoC_TimeStamps/V101.txt'
times = stamp.read_text().splitlines()
assert all(t.isdigit() for t in times)
assert times and all((data / f'mav0/cam{cam}/data/{t}.png').is_file()
                     for cam in (0, 1) for t in times)
a.output.mkdir(parents=True, exist_ok=False)
out = a.output.resolve()
# Native C++ getline retains CR from a Windows checkout. Keep the source intact;
# generate an equivalent LF-only runtime input and record both hashes.
runtime_stamp = out / 'V101-lf.txt'
runtime_stamp.write_bytes(('\n'.join(times) + '\n').encode('ascii'))
command = ['xvfb-run', '-a', '-s', '-screen 0 1280x1024x24',
           str(src / 'Examples/Stereo/stereo_euroc'),
           str(src / 'Vocabulary/ORBvoc.txt'),
           str(src / 'Examples/Stereo/EuRoC.yaml'), str(data), str(runtime_stamp),
           'native_v101']
env = dict(os.environ, LIBGL_ALWAYS_SOFTWARE='1', QT_X11_NO_MITSHM='1')
start = time.monotonic()
record = {'command': command, 'environment_overrides': {k: env[k] for k in
          ('LIBGL_ALWAYS_SOFTWARE', 'QT_X11_NO_MITSHM')},
          'requested_stereo_pairs': len(times), 'timeout_seconds': a.timeout,
          'source_modified': False, 'purpose': 'environment_smoke_not_timing_validation'}
record['timestamp_input'] = {'source': str(stamp),
    'source_sha256': hashlib.sha256(stamp.read_bytes()).hexdigest(),
    'runtime_sha256': hashlib.sha256(runtime_stamp.read_bytes()).hexdigest(),
    'transformation': 'CRLF to LF only; timestamp values unchanged'}
with (out / 'replay.log').open('wb') as log:
    process = subprocess.Popen(command, cwd=out, env=env, stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        record['returncode'] = process.wait(timeout=a.timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        record['returncode'] = process.returncode
        record['timed_out'] = True
record['elapsed_seconds'] = time.monotonic() - start
record['outputs'] = {}
for name in ('f_native_v101.txt', 'kf_native_v101.txt'):
    path = out / name
    if not path.is_file():
        record['outputs'][name] = {'exists': False}
        continue
    rows = [[float(x) for x in line.split()] for line in path.read_text().splitlines() if line.strip()]
    valid = bool(rows) and all(len(row) == 8 and all(map(math.isfinite, row)) for row in rows)
    monotone = bool(rows) and all(x[0] < y[0] for x, y in zip(rows, rows[1:]))
    record['outputs'][name] = {'exists': True, 'rows': len(rows),
        'finite_eight_columns': valid, 'strict_timestamps': monotone,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'first_timestamp': rows[0][0] if rows else None,
        'last_timestamp': rows[-1][0] if rows else None}
record['basic_output_checks_passed'] = record['returncode'] == 0 and all(
    x.get('finite_eight_columns') and x.get('strict_timestamps') for x in record['outputs'].values())
(out / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2), flush=True)
print((out / 'replay.log').read_text(errors='replace')[-3500:], flush=True)
raise SystemExit(0 if record['basic_output_checks_passed'] else 1)
