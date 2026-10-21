"""Run the frozen usability protocol in a fresh WSL workspace; never stage Git.

Each phase writes new directories and refuses overwrite. Commands, hashes and
timeouts are retained. Run phases in order: prepare, compatibility, comparison.
"""
import argparse,csv,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def command(cmd,out,timeout=300):
    out.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();timed_out=False
    with (out/'console.log').open('wb') as f:
        process=subprocess.Popen([str(x) for x in cmd],stdout=f,stderr=subprocess.STDOUT,cwd=out,start_new_session=True)
        try:code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True;os.killpg(process.pid,signal.SIGTERM)
            try:code=process.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);code=process.wait()
    result={'command':[str(x) for x in cmd],'returncode':code,'timeout':timed_out,'seconds':time.monotonic()-start}
    (out/'command.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'run':out.name,**result}),flush=True)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['prepare','compatibility','comparison'])
    p.add_argument('--work',type=Path,required=True);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--protocol',type=Path,required=True)
    p.add_argument('--batch-name',default='usability-runs')
    a=p.parse_args();work=a.work.resolve();src=work/'source';data=a.data.resolve()
    tools=Path(__file__).resolve().parent;protocol=json.loads(a.protocol.read_text())
    assert a.batch_name and all(c.isalnum() or c in '-_' for c in a.batch_name)
    runs=work/a.batch_name;runs.mkdir(exist_ok=True)
    identity=runs/'inputs.json'
    frozen={'protocol_sha256':digest(a.protocol),'protocol':protocol,
            'tools':{t.name:digest(t) for t in [Path(__file__),tools/'run_fixed_replay.py',tools/'score_online_trajectory.py',tools/'opencv_companion.cc']},
            'source':{str(f.relative_to(src)):digest(f) for folder in ['src','include'] for f in (src/folder).rglob('*') if f.is_file()},
            'driver_sha256':digest(src/'Examples/Stereo/stereo_fixed_replay.cc'),
            'data':{f:digest(data/f) for f in ['mav0/cam0/data.csv','mav0/cam1/data.csv','mav0/cam0/sensor.yaml','mav0/imu0/data.csv','mav0/state_groundtruth_estimate0/data.csv']}}
    if identity.exists():assert json.loads(identity.read_text())==frozen,'Inputs changed; use new workspace/batch'
    else:identity.write_text(json.dumps(frozen,indent=2)+'\n')
    if a.phase=='prepare':
        flags=subprocess.check_output(['pkg-config','--cflags','--libs','opencv4'],text=True).split()
        result=command(['g++','-std=c++11','-O2',tools/'opencv_companion.cc','-o',work/'opencv_companion',*flags,'-pthread'],runs/'compile-companion')
        assert result['returncode']==0
        result=command(['cmake','--build',work/'build','--target','mono_euroc','stereo_inertial_euroc','mono_inertial_euroc','rgbd_tum','stereo_tum_vi','--parallel','2'],runs/'compile-native',600)
        assert result['returncode']==0
        return 0
    if a.phase=='compatibility':
        records=[]
        for name,mode,kind,frames,threads in [
            ('fixed-api','fixed','selftest',80,1),
            ('fixed-thread-policy','fixed','instrument',2,2),
            ('native-thread-policy','native_control','instrument',2,2),
            ('native-lifecycle','native_control','native_selftest',80,1),
            ('native-default','native_default','instrument',100,0),
            ('bad-mode','bad_mode','instrument',1,0),
            ('bad-loop','bad_loop','instrument',1,0)]:
            out=runs/name
            result=command([sys.executable,tools/'run_fixed_replay.py','--source',src,'--data',data,
                '--output',out/'replay','--mode',mode,'--kind',kind,'--frames',frames,'--threads',threads],out)
            record={'name':name,**result,'run':json.loads((out/'replay/run.json').read_text())}
            records.append(record)
            (runs/'compatibility.json').write_text(json.dumps(records,indent=2)+'\n')
            if result['returncode']!=0:return 1
        # Official unmodified entry points: mono and both visual-inertial branches.
        timestamps=(src/'Examples/Stereo/EuRoC_TimeStamps/V101.txt').read_text().splitlines()[:1000]
        for folder,binary in [('Monocular','mono_euroc'),('Stereo-Inertial','stereo_inertial_euroc'),('Monocular-Inertial','mono_inertial_euroc')]:
            times=runs/(binary+'-times.txt');times.write_text('\n'.join(timestamps)+'\n')
            out=runs/binary
            result=command(['xvfb-run','-a',src/'Examples'/folder/binary,src/'Vocabulary/ORBvoc.txt',
                src/'Examples'/folder/'EuRoC.yaml',data,times,'compatibility'],out,300)
            poses=out/'f_compatibility.txt';count=0;finite=False
            if poses.exists():
                import numpy as np
                arr=np.loadtxt(poses);count=len(arr);finite=bool(np.isfinite(arr).all())
            record={'name':binary,**result,'exported_frames':count,'all_finite':finite,
                    'accepted_smoke':result['returncode']==0 and count>=100 and finite}
            records.append(record);(runs/'compatibility.json').write_text(json.dumps(records,indent=2)+'\n')
            if not record['accepted_smoke']:return 1
        return 0
    assert (runs/'compatibility.json').exists(),'Run compatibility first'
    compatibility=json.loads((runs/'compatibility.json').read_text())
    assert len(compatibility)==10 and all(r.get('accepted_smoke',r.get('run',{}).get('accepted',False)) for r in compatibility)
    image=data/'mav0/cam0/data'/((src/'Examples/Stereo/EuRoC_TimeStamps/V101.txt').read_text().splitlines()[protocol['offset']]+'.png')
    # Companion-only reference, same fixed image/period as all loaded comparisons.
    alone=runs/'companion-alone'
    r=command([work/'opencv_companion',image,'load.csv',45],alone,60)
    assert r['returncode']==0
    records=[]
    for load in protocol['loads']:
        for repeat in range(protocol['repetitions']):
            strategies=protocol['strategies'][repeat:]+protocol['strategies'][:repeat]
            for strategy in strategies:
                name=f'{load}-{repeat+1}-{strategy}';out=runs/name
                companion=None
                if load=='opencv_companion':
                    # Separate explicitly configured process. No global core/priority settings.
                    companion=subprocess.Popen([str(work/'opencv_companion'),str(image),str(runs/(name+'-load.csv')),'180'])
                    time.sleep(.2)
                try:
                    result=command([sys.executable,tools/'run_fixed_replay.py','--source',src,'--data',data,
                        '--output',out/'replay','--mode','native_control' if strategy=='native_control' else 'fixed',
                        '--frames',protocol['evaluation_frames'],'--offset',protocol['offset'],
                        '--init-limit',protocol['initialization_limit'],'--preload-limit',protocol['preload_limit'],
                        '--period-ns',protocol['h_ns'],'--threads',protocol['process_threads'],
                        '--spin-us',protocol['hybrid_spin_us'] if strategy=='fixed_hybrid' else 0],out,240)
                finally:
                    if companion:
                        companion.terminate();companion.wait(timeout=10)
                run=json.loads((out/'replay/run.json').read_text())
                record={'name':name,'strategy':strategy,'load':load,'repeat':repeat+1,**result,'run':run}
                records.append(record);(runs/'comparison.json').write_text(json.dumps(records,indent=2)+'\n')
                if result['returncode']!=0:return 1 # implementation/input failure, not a method win/loss
    return 0

if __name__=='__main__':raise SystemExit(main())
