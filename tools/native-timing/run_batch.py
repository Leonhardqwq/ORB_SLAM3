"""Serial, checkpointed native KITTI runs; no Git/index operations."""
import argparse
import csv
import hashlib
import json
import os
import platform
import random
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2)+'\n')


def resource(pid):
    try:
        values = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()
        status = Path(f'/proc/{pid}/status').read_text().splitlines()
        rss = next((int(s.split()[1]) for s in status if s.startswith('VmRSS:')), 0)
        threads = next((int(s.split()[1]) for s in status if s.startswith('Threads:')), 0)
        return (int(values[11])+int(values[12]))/os.sysconf('SC_CLK_TCK'), rss, threads
    except (FileNotFoundError, ProcessLookupError):
        return 0, 0, 0


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--protocol', type=Path, required=True)
    ap.add_argument('--phase', choices=['pilot','overhead','formal'], required=True)
    ap.add_argument('--attempt', type=int, default=1, help='New directory for a repaired pilot; old attempts remain')
    a=ap.parse_args()
    root=a.root.resolve(); p=json.loads(a.protocol.read_text())
    source=root/'source'; binary=root/'builds/observer/native_kitti'; data=root/'data/kitti'
    phase=a.phase if a.attempt==1 else f'{a.phase}-{a.attempt:02d}'
    dest=root/'runs'/p['batch']/phase
    dest.mkdir(parents=True,exist_ok=True)
    fingerprint={str(f.relative_to(root)):sha(f) for f in [binary,source/'lib/libORB_SLAM3.so',
        source/'Examples/Stereo/KITTI00-02.yaml',source/'Examples/Stereo/KITTI04-12.yaml',
        root/'tools/native_kitti.cc',root/'tools/run_batch.py',data/'summary.json']}
    plan=[]
    if a.phase=='pilot':
        plan=[dict(sequence='05',mode=m,repeat=1,observation='full',frames=200) for m in p['playback_modes']]
    elif a.phase=='overhead':
        for rep in range(1,4):
            for obs in (['minimal','full'] if rep%2 else ['full','minimal']):
                plan.append(dict(sequence='05',mode='upstream',repeat=rep,observation=obs,frames=200))
    else:
        rng=random.Random(p['order_seed'])
        for mode in p['playback_modes']:
            for rep in range(1,p['repetitions']+1):
                sequences=p['sequences'].copy(); rng.shuffle(sequences)
                for seq in sequences:
                    plan.append(dict(sequence=seq,mode=mode,repeat=rep,observation='full',frames=0))
    frozen=dict(protocol=p,fingerprint=fingerprint,plan=plan)
    frozen_path=dest/'frozen.json'
    if frozen_path.exists():
        if json.loads(frozen_path.read_text())!=frozen:
            raise RuntimeError('Resume requires identical protocol, tools, data and binaries')
    else:
        write_json(frozen_path,frozen)
    env=dict(platform=platform.platform(),python=platform.python_version(),
             cpu=Path('/proc/cpuinfo').read_text(),memory=Path('/proc/meminfo').read_text(),
             affinity=sorted(os.sched_getaffinity(0)),
             environment={k:v for k,v in os.environ.items() if k.startswith(('OMP_','OPENBLAS_','MKL_'))})
    if not (dest/'environment.json').exists(): write_json(dest/'environment.json',env)
    for number,job in enumerate(plan,1):
        name=f'{number:02d}-{job["mode"]}-s{job["sequence"]}-r{job["repeat"]}-{job["observation"]}'
        run=dest/name
        if run.exists():
            result=json.loads((run/'result.json').read_text())
            if result['status']!='running':
                print('preserve completed attempt',name,result['status'],flush=True); continue
            raise RuntimeError(f'Interrupted record retained at {run}; inspect it before a new batch')
        run.mkdir()
        config='KITTI00-02.yaml' if int(job['sequence'])<=2 else 'KITTI04-12.yaml'
        cmd=[str(binary),str(source/'Vocabulary/ORBvoc.txt'),str(source/'Examples/Stereo'/config),
             str(data/'sequences'/job['sequence']),job['mode'],job['observation'],str(job['frames']),str(run)]
        result=dict(job,status='running',command=cmd,started_utc=datetime.now(timezone.utc).isoformat())
        write_json(run/'result.json',result)
        print(f'{number}/{len(plan)} start {name}',flush=True)
        start=time.monotonic(); peak=0; timedout=False
        with (run/'process.log').open('w') as log, (run/'resources.csv').open('w') as res:
            proc=subprocess.Popen(cmd,cwd=run,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            writer=csv.writer(res); writer.writerow(['wall_s','process_cpu_s','rss_kib','threads','host_load1'])
            while proc.poll() is None:
                elapsed=time.monotonic()-start
                cpu,rss,threads=resource(proc.pid); peak=max(peak,rss)
                writer.writerow([elapsed,cpu,rss,threads,os.getloadavg()[0]]); res.flush()
                if elapsed>p['run_timeout_seconds']:
                    timedout=True; os.killpg(proc.pid,signal.SIGTERM)
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL)
                    break
                time.sleep(p['resource_interval_seconds'])
            code=proc.wait()
        frames=0
        if (run/'frames.csv').exists():
            with (run/'frames.csv').open() as f: frames=max(0,sum(1 for _ in f)-1)
        expected=job['frames'] or len((data/'sequences'/job['sequence']/'times.txt').read_text().splitlines())
        status='timeout' if timedout else ('completed' if code==0 and frames==expected and (run/'runner.json').exists() else 'execution_error')
        result.update(status=status,exit_code=code,wall_seconds=time.monotonic()-start,frames=frames,
                      expected_frames=expected,peak_sampled_rss_mib=peak/1024,finished_utc=datetime.now(timezone.utc).isoformat())
        if (run/'runner.json').exists(): result['runner']=json.loads((run/'runner.json').read_text())
        write_json(run/'result.json',result)
        print(f'{number}/{len(plan)} finish {name} {status} frames={frames} wall={result["wall_seconds"]:.1f}s',flush=True)
        time.sleep(p['pause_between_runs_seconds'])
    write_json(dest/'finished.json',dict(finished_utc=datetime.now(timezone.utc).isoformat(),attempts=len(plan)))


if __name__=='__main__': main()
