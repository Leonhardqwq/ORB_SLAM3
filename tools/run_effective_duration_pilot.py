"""Execute E2 only, using existing built source in WSL; refuse output overwrite."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import re
import subprocess
import sys

from check_effective_events import audit, sha
from run_usability_batch import command


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'data', 'output', 'protocol', 'reference', 'authoritative-source'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    cfg = json.loads(a.protocol.read_text(encoding='utf-8'))
    a.output.mkdir(parents=True, exist_ok=False)
    tools = Path(__file__).resolve().parent
    source = a.source.resolve()
    selected = list(source.glob('src/*.cc')) + list(source.glob('include/*.h'))
    selected += [source/'Examples/Stereo/stereo_fixed_replay.cc', source/'CMakeLists.txt']
    for f in selected:
        if f.read_bytes() != (a.authoritative_source / f.relative_to(source)).read_bytes():
            raise ValueError('source differs: '+str(f))
    dependencies = subprocess.check_output(['ldd', str(source/'Examples/Stereo/stereo_fixed_replay')], text=True)
    match = re.search(r'libORB_SLAM3\.so\s+=>\s+(.*?)\s+\(', dependencies)
    if not match or 'not found' in dependencies:
        raise ValueError('unresolved runtime dependency')
    library = Path(match[1]).resolve()
    library_source = library.parent.parent
    for f in selected:
        if f.parent.name in ('src', 'include') and f.read_bytes() != (library_source/f.relative_to(source)).read_bytes():
            raise ValueError('linked library source differs: '+str(f))
    inputs = {'protocol': cfg, 'protocol_sha256': sha(a.protocol), 'data_role': 'measurement_pilot',
              'source': {f.relative_to(source).as_posix(): sha(f) for f in selected},
              'binary_sha256': sha(source/'Examples/Stereo/stereo_fixed_replay'),
              'library': str(library), 'library_sha256': sha(library),
              'reference_sha256': sha(a.reference),
              'tools': {s: sha(tools/s) for s in ['run_effective_duration_pilot.py', 'check_effective_events.py',
                        'run_fixed_replay.py', 'run_usability_batch.py']},
              'data': {s: sha(a.data/s) for s in ['mav0/cam0/data.csv', 'mav0/cam1/data.csv',
                                               'mav0/state_groundtruth_estimate0/data.csv']}}
    (a.output/'inputs.json').write_text(json.dumps(inputs, indent=2)+'\n')
    (a.output/'dependencies.txt').write_text(dependencies)
    records = []
    for name in cfg['order']:
        kind = name.split('-')[1]
        directory = a.output/name
        cmd = [sys.executable, tools/'run_fixed_replay.py', '--source', source,
               '--data', a.data, '--output', directory/'replay', '--mode', 'fixed', '--kind', kind,
               '--frames', cfg['evaluation_frames'], '--offset', cfg['offset'],
               '--init-limit', cfg['initialization_limit'], '--preload-limit', cfg['preload_limit'],
               '--period-ns', cfg['h_ns'], '--threads', cfg['process_threads'],
               '--spin-us', cfg['spin_us'], '--timeout', cfg['timeout_seconds']]
        execution = command(cmd, directory, cfg['timeout_seconds'] + 15)
        runpath = directory/'replay/run.json'
        run = json.loads(runpath.read_text()) if runpath.exists() else {}
        record = {'name': name, 'kind': kind, 'execution': execution, 'run': run}
        records.append(record)
        (a.output/'runs.json').write_text(json.dumps(records, indent=2)+'\n')
        if execution['returncode'] or not run.get('accepted'):
            (a.output/'stop.json').write_text(json.dumps({'stage': 'E2', 'reason': 'acquisition_failure', 'run': name}))
            return 1
        if kind == 'instrument':
            result, _ = audit(directory/'replay', cfg, a.reference)
            record['accounting'] = result
            (directory/'accounting.json').write_text(json.dumps(result, indent=2)+'\n')
            if result['status'] != 'accounting_passed':
                (a.output/'stop.json').write_text(json.dumps({'stage':'E2', 'reason':'accounting_failure','run':name}))
                return 1
        (a.output/'runs.json').write_text(json.dumps(records, indent=2)+'\n')
    wall = {kind: [r['run']['replay']['evaluation_elapsed_ns'] for r in records if r['kind']==kind]
            for kind in ('plain', 'instrument')}
    cpu = {kind: [r['run']['replay']['evaluation_cpu_ns'] for r in records if r['kind']==kind]
           for kind in ('plain', 'instrument')}
    ratio = statistics.median(wall['instrument']) / statistics.median(wall['plain'])
    result = {'stage':'E2', 'status':'passed' if ratio <= 1 + cfg['instrumentation_overhead_limit'] else 'failed',
              'runs':len(records), 'wall_ns':wall, 'cpu_ns':cpu, 'wall_median_ratio':ratio,
              'cpu_median_ratio': statistics.median(cpu['instrument'])/statistics.median(cpu['plain']),
              'interpretation':'Wall-time gate includes waiting; neither a CPU bound nor probabilistic validation',
              'probability_stage':'not_entered'}
    (a.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
