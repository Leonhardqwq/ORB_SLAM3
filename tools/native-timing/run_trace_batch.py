"""Serial native diagnostic runs; event collection is controlled by an env var."""
import argparse
import csv
import hashlib
import json
import os
import random
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--phase',choices=['pilot','overhead','formal'],required=True)
    ap.add_argument('--protocol',type=Path,required=True)
    args=ap.parse_args();root=args.root;work=root/'trace-2026-10-29'
    source=work/'source-v2';binary=work/'observer/native_kitti'
    protocol=json.loads(args.protocol.read_text())
    dest=work/'runs'/args.phase;dest.mkdir(parents=True,exist_ok=True)
    jobs=[]
    if args.phase=='pilot':jobs=[dict(sequence='07',repeat=1,trace=True,frames=100)]
    elif args.phase=='overhead':
        for repeat in range(1,4):
            for enabled in ([False,True] if repeat%2 else [True,False]):
                jobs.append(dict(sequence='07',repeat=repeat,trace=enabled,frames=200))
    else:
        rng=random.Random(20261029)
        for repeat in range(1,4):
            seqs=['01','05','07'];rng.shuffle(seqs)
            jobs.extend(dict(sequence=seq,repeat=repeat,trace=True,frames=0) for seq in seqs)
    frozen={'protocol':protocol,'jobs':jobs,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'library_sha256':hashlib.sha256((source/'lib/libORB_SLAM3.so').read_bytes()).hexdigest(),
            'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if (dest/'frozen.json').exists():
        if json.loads((dest/'frozen.json').read_text())!=frozen:raise RuntimeError('Changed resume inputs')
    else:write(dest/'frozen.json',frozen)
    for number,job in enumerate(jobs,1):
        run=dest/f'{number:02d}-s{job["sequence"]}-r{job["repeat"]}-trace{int(job["trace"])}'
        if (run/'result.json').exists():
            previous=json.loads((run/'result.json').read_text())
            if previous['status']=='running':raise RuntimeError(f'Inspect interrupted attempt {run}')
            continue
        run.mkdir()
        config='KITTI00-02.yaml' if job['sequence']=='01' else 'KITTI04-12.yaml'
        command=[str(binary),str(source/'Vocabulary/ORBvoc.txt'),str(source/'Examples/Stereo'/config),
                 str(root/'data/kitti/sequences'/job['sequence']),'periodic','full',str(job['frames']),str(run)]
        env=os.environ.copy();env.pop('ORB_NATIVE_TRACE',None)
        if job['trace']:env['ORB_NATIVE_TRACE']=str(run/'events.csv')
        result={**job,'status':'running','command':command,'started_utc':datetime.now(timezone.utc).isoformat()}
        write(run/'result.json',result);print('start',run.name,flush=True)
        start=time.monotonic()
        with (run/'process.log').open('w') as log,(run/'resources.csv').open('w') as resource:
            writer=csv.writer(resource);writer.writerow(['monotonic_ns','rss_kib','threads'])
            proc=subprocess.Popen(command,cwd=run,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            while proc.poll() is None:
                try:
                    status=Path(f'/proc/{proc.pid}/status').read_text().splitlines()
                    rss=next((int(x.split()[1]) for x in status if x.startswith('VmRSS:')),0)
                    threads=next((int(x.split()[1]) for x in status if x.startswith('Threads:')),0)
                    writer.writerow([time.monotonic_ns(),rss,threads])
                except FileNotFoundError:pass
                if time.monotonic()-start>1800:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL)
                    break
                time.sleep(1)
            code=proc.wait()
        with (run/'frames.csv').open() as f:frames=max(0,sum(1 for _ in f)-1)
        expected=job['frames'] or len((root/'data/kitti/sequences'/job['sequence']/'times.txt').read_text().splitlines())
        result.update(status='completed' if code==0 and frames==expected else 'execution_error',exit_code=code,
                      frames=frames,expected_frames=expected,wall_seconds=time.monotonic()-start,
                      finished_utc=datetime.now(timezone.utc).isoformat())
        write(run/'result.json',result);print('finish',run.name,result['status'],frames,flush=True)
        time.sleep(5)
    write(dest/'finished.json',{'attempts':len(jobs),'finished_utc':datetime.now(timezone.utc).isoformat()})


if __name__=='__main__':main()
