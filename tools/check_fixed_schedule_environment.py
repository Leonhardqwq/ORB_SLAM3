#!/usr/bin/env python3
"""Configure the unmodified baseline; do not install dependencies or build SLAM.

Use a NEW output directory. Configuration success is not build/run acceptance.
Raw logs/cache belong in an ignored build directory, not in Git.
"""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--cc', required=True)
    parser.add_argument('--cxx', required=True)
    parser.add_argument('--ninja', required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if not (source / 'src/System.cc').is_file():
        parser.error('source must be an ORB_SLAM3 checkout')
    if output.exists():
        parser.error('output must be new; previous evidence is never overwritten')
    if output == source or output in source.parents:
        parser.error('output must not contain the source checkout')
    output.mkdir(parents=True)
    git = ['git', '--no-optional-locks', '-c', 'safe.directory=' + source.as_posix(),
           '-C', str(source)]
    def git_read(*options):
        return subprocess.check_output(git + list(options), text=True).strip()
    record = {
        'purpose': 'baseline_configuration_only',
        'platform': platform.platform(), 'python': sys.version,
        'source': str(source), 'branch': git_read('branch', '--show-current'),
        'head': git_read('rev-parse', 'HEAD'),
        'worktree_status_before': git_read('status', '--short'),
        'source_sha256': {},
    }
    for rel in ['CMakeLists.txt', 'src/System.cc', 'src/Tracking.cc',
                'src/LocalMapping.cc', 'src/LoopClosing.cc', 'src/Frame.cc',
                'src/Atlas.cc', 'src/KeyFrameDatabase.cc', 'src/Optimizer.cc']:
        record['source_sha256'][rel] = hashlib.sha256((source / rel).read_bytes()).hexdigest()
    command = [args.cmake, '-S', str(source), '-B', str(output / 'cmake'), '-G', 'Ninja',
               '-DCMAKE_MAKE_PROGRAM=' + args.ninja,
               '-DCMAKE_C_COMPILER=' + args.cc, '-DCMAKE_CXX_COMPILER=' + args.cxx]
    record['command'] = command
    started = time.monotonic()
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=120, check=False)
        raw, returncode = result.stdout, result.returncode
        record['status'] = 'configured_only' if returncode == 0 else 'configuration_failed'
    except subprocess.TimeoutExpired as exc:
        raw, returncode = exc.stdout or b'', 124
        record['status'] = 'configuration_timeout'
    except OSError as exc:
        raw, returncode = str(exc).encode('utf-8'), 127
        record['status'] = 'tool_unavailable'
    record['returncode'] = returncode
    record['elapsed_seconds'] = time.monotonic() - started
    record['build_attempted'] = False
    record['runtime_attempted'] = False
    (output / 'configure.log').write_bytes(raw)
    record['log_sha256'] = hashlib.sha256(raw).hexdigest()
    record['source_unchanged'] = all(
        hashlib.sha256((source / rel).read_bytes()).hexdigest() == sha
        for rel, sha in record['source_sha256'].items())
    (output / 'environment.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': record['status'], 'returncode': returncode,
                      'output': str(output), 'source_unchanged': record['source_unchanged']},
                     ensure_ascii=False))
    return returncode


if __name__ == '__main__':
    raise SystemExit(main())
