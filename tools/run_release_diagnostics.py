"""Serial, predeclared release diagnostics with a standalone companion before/after each co-load replay."""
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def environment():
    names=['/proc/loadavg','/proc/stat','/proc/pressure/cpu','/proc/sys/kernel/perf_event_paranoid']
    return {n:Path(n).read_text() for n in names if Path(n).exists()}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['source','data','output','protocol','companion','support-tools']:
        p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--phase',choices=['smoke','timeline','context'],required=True)
    a=p.parse_args();sys.path.insert(0,str(a.support_tools));from run_usability_batch import command
    cfg=json.loads(a.protocol.read_text());tools=Path(__file__).resolve().parent
    a.output.mkdir(parents=True,exist_ok=False)
    source=a.source.resolve(); data=a.data.resolve();out=a.output.resolve()
    frozen={'protocol':cfg,'protocol_sha256':sha(a.protocol),'phase':a.phase,'environment':environment(),
        'tools':{str(t):sha(t) for t in [Path(__file__),tools/'run_fixed_replay.py',a.support_tools/'run_usability_batch.py']},
        'source':{str(t):sha(t) for name in ['src','include'] for t in (source/name).rglob('*') if t.is_file()},
        'driver_sha256':sha(source/'Examples/Stereo/stereo_fixed_replay.cc'),
        'binary_sha256':sha(source/'Examples/Stereo/stereo_fixed_replay'), 'companion_sha256':sha(a.companion)}
    (out/'inputs.json').write_text(json.dumps(frozen,indent=2)+'\n')
    stamp=(source/'Examples/Stereo/EuRoC_TimeStamps/V101.txt').read_text().splitlines()[cfg['offset']]
    image=data/'mav0/cam0/data'/(stamp+'.png')
    assert image.is_file(), 'required companion input missing'
    (out/'companion-input.json').write_text(json.dumps({'path':str(image),'sha256':sha(image)},indent=2))
    if a.phase=='smoke':
        schedule=[('idle',j,'fixed_hybrid',j) for j in range(3)]
    elif a.phase=='context':
        schedule=[('idle',j+1,'fixed_hybrid',2) for j in range(cfg['repetitions'])]
    else:
        schedule=[(load,j+1,strategy,1) for load in cfg['loads'] for j,order in enumerate(cfg['orders']) for strategy in order]
    records=[]
    for load,repeat,strategy,diagnostics in schedule:
        name=f'{load}-{repeat}-{strategy}';directory=out/name
        before=environment();compan=None;companion_log=None;baselines={}
        if load=='opencv_companion':
            for label in ['before']:
                target=out/(name+'-'+label)
                result=command([a.companion,image,target/'load.csv',cfg['companion_baseline_seconds']],target,60)
                if result['returncode']:return 1
                baselines[label]=result
            companion_log=(out/(name+'-load.log')).open('wb')
            compan=subprocess.Popen([str(a.companion),str(image),str(out/(name+'-load.csv')),'180'],
                stdout=companion_log,stderr=subprocess.STDOUT)
            time.sleep(.2)
        try:
            frames=2 if a.phase=='smoke' else cfg['evaluation_frames']
            result=command([sys.executable,tools/'run_fixed_replay.py','--source',source,'--data',data,
                '--output',directory/'replay','--mode','native_control' if strategy=='native_control' else 'fixed',
                '--frames',frames,'--offset',cfg['offset'],'--init-limit',cfg['initialization_limit'],
                '--preload-limit',frames+cfg['initialization_limit']+1,'--period-ns',cfg['h_ns'],
                '--threads',cfg['process_threads'],'--spin-us',cfg['hybrid_spin_us'] if strategy=='fixed_hybrid' else 0,
                '--release-diagnostics',diagnostics],directory,240)
        finally:
            if compan:
                compan.terminate()
                try:compan.wait(timeout=10)
                except subprocess.TimeoutExpired:compan.kill();compan.wait()
                companion_log.close()
        if load=='opencv_companion':
            target=out/(name+'-after')
            baselines['after']=command([a.companion,image,target/'load.csv',cfg['companion_baseline_seconds']],target,60)
            if baselines['after']['returncode']:return 1
        record={'name':name,'strategy':strategy,'load':load,'repeat':repeat,'diagnostics':diagnostics,
            **result,'run':json.loads((directory/'replay/run.json').read_text()),
            'companion_baselines':baselines,'environment_before':before,'environment_after':environment()}
        if compan:record['companion_returncode']=compan.returncode
        records.append(record);(out/'runs.json').write_text(json.dumps(records,indent=2)+'\n')
        print('COMPLETE',name,'diagnostics',diagnostics,flush=True)
        if result['returncode'] or (compan and compan.returncode!=0):return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
