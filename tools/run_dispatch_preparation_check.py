"""Compare record preparation before/after waiting using one binary, all other options fixed."""
import argparse,hashlib,json,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['source','data','output','protocol','base-protocol','support-tools']:
        p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();sys.path.insert(0,str(a.support_tools));from run_usability_batch import command
    cfg=json.loads(a.base_protocol.read_text());dispatch=json.loads(a.protocol.read_text())
    a.output.mkdir(parents=True,exist_ok=False);runs=a.output.resolve();source=a.source.resolve()
    tools=Path(__file__).resolve().parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    (runs/'inputs.json').write_text(json.dumps({'protocol':cfg,'dispatch_protocol':dispatch,'phase':'dispatch',
        'driver_sha256':sha(source/'Examples/Stereo/stereo_fixed_replay.cc'),
        'binary_sha256':sha(source/'Examples/Stereo/stereo_fixed_replay'),
        'run_script_sha256':sha(tools/'run_fixed_replay.py'),'entry_sha256':sha(Path(__file__)),
        'protocol_sha256':sha(a.protocol),'base_protocol_sha256':sha(a.base_protocol)},indent=2))
    records=[]
    for repeat,order in enumerate(dispatch['orders'],1):
        for prepared in order:
            assert prepared in [0,1]
            strategy='fixed_prepared' if prepared else 'fixed_legacy';name=f'idle-{repeat}-{strategy}';directory=runs/name
            cmd=[sys.executable,tools/'run_fixed_replay.py','--source',source,'--data',a.data,'--output',directory/'replay',
                '--frames',cfg['evaluation_frames'],'--offset',cfg['offset'],'--init-limit',cfg['initialization_limit'],
                '--preload-limit',cfg['preload_limit'],'--period-ns',cfg['h_ns'],'--threads',cfg['process_threads'],
                '--spin-us',cfg['hybrid_spin_us'],'--release-diagnostics',1,'--prepare-before-wait',prepared]
            result=command(cmd,directory,240);run=json.loads((directory/'replay/run.json').read_text())
            records.append({'name':name,'strategy':strategy,'load':'idle','repeat':repeat,'diagnostics':1,
                'prepare_before_wait':prepared,**result,'run':run})
            (runs/'runs.json').write_text(json.dumps(records,indent=2)+'\n')
            if result['returncode']:return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
