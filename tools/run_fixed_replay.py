"""Run one real replay; keep inputs, output and resource evidence in a new directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['fixed','native_control','native_default','bad_mode','bad_loop'],default='fixed')
    p.add_argument('--serial-stereo',type=int,choices=[0,1],default=1)
    p.add_argument('--synchronous-loop',type=int,choices=[0,1],default=0)
    p.add_argument('--kind',choices=['instrument','plain','selftest','native_selftest'],default='instrument')
    p.add_argument('--frames',type=int,default=400)
    p.add_argument('--settings',type=Path)
    p.add_argument('--timestamps',type=Path)
    p.add_argument('--period-ns',type=int,default=50000000)
    p.add_argument('--spin-us',type=int,default=0)
    p.add_argument('--prepare-before-wait',type=int,choices=[0,1],default=0)
    p.add_argument('--release-diagnostics',type=int,choices=[0,1,2],default=0)
    p.add_argument('--workload-diagnostics',type=int,choices=[0,1],default=0)
    p.add_argument('--work-control',type=int,choices=[0,1,2,3,4,5,6,7],default=0)
    p.add_argument('--defer-routine-keyframes',type=int,choices=[0,1],default=0)
    p.add_argument('--global-ba-iterations',type=int,default=0)
    p.add_argument('--backend-keyframes',type=int,default=0)
    p.add_argument('--backend-points',type=int,default=0)
    p.add_argument('--extraction-cell-candidates',type=int,default=0)
    p.add_argument('--backend-fixed-keyframes',type=int,default=0)
    p.add_argument('--maintenance-keyframes',type=int,default=0)
    p.add_argument('--keyframe-period',type=int,default=0)
    p.add_argument('--policy-seed',type=int,default=20261019)
    p.add_argument('--tracking-diagnostics',type=int,choices=[0,1],default=0)
    p.add_argument('--offset',type=int,default=0)
    p.add_argument('--init-limit',type=int,default=100)
    p.add_argument('--preload-limit',type=int,default=0)
    p.add_argument('--threads',type=int,default=0,help='Explicit process policy; 0 preserves inherited settings')
    p.add_argument('--timeout',type=int,default=300)
    p.add_argument('--cpu-affinity',help='Optional explicit Linux virtual CPUs, e.g. 0,2; no reservation')
    p.add_argument('--resource-diagnostics',type=int,choices=[0,1],default=0)
    a=p.parse_args()
    from replay_resources import parse_cpus, launch_command, system_snapshot, Recorder
    cpus=parse_cpus(a.cpu_affinity,os.sched_getaffinity(0)) if a.cpu_affinity is not None else None
    environment_snapshot=system_snapshot() if a.resource_diagnostics or cpus is not None else None
    a.output.mkdir(parents=True,exist_ok=False)
    out=a.output.resolve();src=a.source.resolve()
    original_settings=(a.settings or src/'Examples/Stereo/EuRoC.yaml').resolve()
    timestamps=(a.timestamps or src/'Examples/Stereo/EuRoC_TimeStamps/V101.txt').resolve()
    config=original_settings.read_text()
    if a.mode!='native_default':
        config=re.sub(r'^(loopClosing|Execution\.(mode|serialStereo|managedNoLoop|synchronousLoop)):.*(?:\n|$)','',config,flags=re.M)
        mode='native_async' if a.mode=='native_control' else 'invalid_mode' if a.mode=='bad_mode' else 'fixed_stereo'
        config+=f'\nExecution.mode: "{mode}"\nExecution.serialStereo: {a.serial_stereo}\nExecution.synchronousLoop: {a.synchronous_loop}\nExecution.managedNoLoop: {1 if a.mode=="native_control" else 0}\nloopClosing: {1 if a.mode=="bad_loop" or a.synchronous_loop else 0}\n'
    settings=out/'settings.yaml';settings.write_text(config)
    cmd=[str(src/'Examples/Stereo/stereo_fixed_replay'),str(src/'Vocabulary/ORBvoc.txt'),
         str(settings),str(a.data.resolve()),str(timestamps),
         str(out/'replay'),a.kind,str(a.frames),
         '--period-ns',str(a.period_ns),'--spin-us',str(a.spin_us),'--offset',str(a.offset),
         '--init-limit',str(a.init_limit),'--preload-limit',str(a.preload_limit),
         '--cv-threads',str(a.threads),'--eigen-threads',str(a.threads)]
    if a.work_control:cmd+=['--work-control',str(a.work_control),'--policy-seed',str(a.policy_seed)]
    if a.defer_routine_keyframes:cmd+=['--defer-routine-keyframes',str(a.defer_routine_keyframes)]
    if a.global_ba_iterations:cmd+=['--global-ba-iterations',str(a.global_ba_iterations)]
    if a.backend_keyframes or a.backend_points:cmd+=['--backend-keyframes',str(a.backend_keyframes),'--backend-points',str(a.backend_points)]
    if a.extraction_cell_candidates:cmd+=['--extraction-cell-candidates',str(a.extraction_cell_candidates)]
    if a.backend_fixed_keyframes:cmd+=['--backend-fixed-keyframes',str(a.backend_fixed_keyframes)]
    if a.maintenance_keyframes:cmd+=['--maintenance-keyframes',str(a.maintenance_keyframes)]
    if a.keyframe_period:cmd+=['--keyframe-period',str(a.keyframe_period)]
    if a.tracking_diagnostics:cmd+=['--tracking-diagnostics',str(a.tracking_diagnostics)]
    if a.workload_diagnostics:cmd+=['--workload-diagnostics',str(a.workload_diagnostics)]
    if a.release_diagnostics:cmd+=['--release-diagnostics',str(a.release_diagnostics)]
    if a.prepare_before_wait:cmd+=['--prepare-before-wait',str(a.prepare_before_wait)]
    cmd=launch_command(cmd,cpus)
    resource_record=Recorder(out/'resource-samples.csv',cpus,src/'Examples/Stereo/stereo_fixed_replay') if a.resource_diagnostics else None
    overrides={k:str(a.threads) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']} if a.threads else {}
    start=time.monotonic();rss=0;threads=0;timed_out=False
    with (out/'console.log').open('wb') as log:
        child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,cwd=out,
                               env=dict(os.environ,**overrides),start_new_session=True)
        while child.poll() is None:
            try:
                status=Path(f'/proc/{child.pid}/status').read_text()
                if resource_record:resource_record.observe(child.pid,status)
                m=re.search(r'^VmRSS:\s+(\d+)',status,re.M)
                if m:rss=max(rss,int(m.group(1))*1024)
                m=re.search(r'^Threads:\s+(\d+)',status,re.M)
                if m:threads=max(threads,int(m.group(1)))
            except FileNotFoundError:pass
            if time.monotonic()-start>a.timeout:
                timed_out=True;os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                break
            time.sleep(0.02)
    elapsed=time.monotonic()-start
    hashes={}
    for pattern in ['src/*.cc','include/*.h','Examples/Stereo/stereo_fixed_replay.cc','CMakeLists.txt']:
        for path in src.glob(pattern): hashes[str(path.relative_to(src))]=hashlib.sha256(path.read_bytes()).hexdigest()
    record={'command':cmd,'mode':a.mode,'kind':a.kind,'returncode':child.returncode,
            'timed_out':timed_out,'seconds':elapsed,'sampled_peak_RSS_bytes':rss,
            'sampled_peak_threads':threads,'resource_sample_interval_seconds':0.02,
            'environment_overrides':overrides,'source_hashes':hashes,
            'original_settings':str(original_settings),'timestamps':str(timestamps),
            'original_settings_sha256':hashlib.sha256(original_settings.read_bytes()).hexdigest(),
            'timestamps_sha256':hashlib.sha256(timestamps.read_bytes()).hexdigest(),
            'config_sha256':hashlib.sha256(settings.read_bytes()).hexdigest()}
    record['resource_environment']=environment_snapshot
    record['requested_cpu_affinity']=cpus
    record['resource_diagnostics']=resource_record.finish() if resource_record else None
    binary=src/'Examples/Stereo/stereo_fixed_replay'
    linked=subprocess.run(['ldd',str(binary)],capture_output=True,text=True)
    record['binary_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
    record['ldd']=linked.stdout
    match=re.search(r'libORB_SLAM3.so => (\S+)',linked.stdout)
    if match:
        lib=Path(match.group(1)).resolve()
        record['loaded_library']={'path':str(lib),'sha256':hashlib.sha256(lib.read_bytes()).hexdigest()}
    summary=out/'replay-summary.json' 
    if summary.exists():
        try:record['replay']=json.loads(summary.read_text())
        except json.JSONDecodeError:record['replay']='incomplete_json'
    expected_error={'bad_mode':'Unknown Execution.mode','bad_loop':'fixed_stereo requires'}
    if a.mode in expected_error:
        record['accepted']=child.returncode!=0 and expected_error[a.mode] in (out/'console.log').read_text(errors='replace') and not timed_out
        record['purpose']='expected_rejection'
    else:record['accepted']=child.returncode==0 and record.get('replay',{}).get('status')=='passed'
    if resource_record and record['resource_diagnostics']['errors']:
        record['accepted']=False
    (out/'run.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ['source_hashes','command']},indent=2),flush=True)
    if not record['accepted']:print((out/'console.log').read_text(errors='replace')[-4000:],flush=True)
    return 0 if record['accepted'] else 1

if __name__=='__main__':raise SystemExit(main())
