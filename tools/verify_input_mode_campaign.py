"""Sequential regression checks after timed collection, with retained commands."""
import argparse,json,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser()
for n in ['source','repository','paper','output','data-root','campaign']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
state=json.loads((a.campaign/'results.json').read_text())
if state['status']!='completed_diagnostic_collection':raise ValueError('Wait for timed collection')
checks=[]
def call(label,cmd,cwd,expected=0):
    start=time.monotonic();r=subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=240)
    (a.output/(label+'.log')).write_text(r.stdout)
    checks.append({'label':label,'command':cmd,'returncode':r.returncode,'seconds':time.monotonic()-start,'passed':r.returncode==expected})
    (a.output/'verification.json').write_text(json.dumps({'checks':checks},indent=2))
    print(label,checks[-1]['passed'],flush=True)
    if r.returncode!=expected:raise RuntimeError(r.stdout[-2500:])
call('analysis-tests',[sys.executable,'-B','-m','unittest','test_model_readiness.py','test_input_modes.py'],a.paper/'experiments/orb-slam3')
call('probe-and-accounting-tests',[sys.executable,'-B','-m','unittest','test_input_workload.py','test_effective_events.py','test_contained_backend.py'],a.repository/'tools')
for mode,kind,label in [('fixed','selftest','fixed-lifecycle'),('native_default','native_selftest','native-lifecycle')]:
    cmd=[sys.executable,str(a.repository/'tools/run_fixed_replay.py'),'--source',str(a.source),'--data',str(a.data_root/'V1_01_easy'),
         '--output',str(a.output/label),'--mode',mode,'--kind',kind,'--serial-stereo','0','--synchronous-loop','1' if mode=='fixed' else '0',
         '--frames','80','--offset','0','--init-limit','100','--preload-limit','201','--threads','1','--timeout','180',
         '--timestamps',str(a.source/'Examples/Stereo/EuRoC_TimeStamps/V101.txt')]
    call(label,cmd,a.output)
    r=json.loads((a.output/label/'run.json').read_text())
    checks[-1]['self_checks']=r['replay']['self_checks'];checks[-1]['workload_disabled']=r['replay']['workload_diagnostics']==0
    if not checks[-1]['workload_disabled']:raise RuntimeError('Default probe enabled')
# Invalid diagnostic kind must fail before consuming images.
binary=a.source/'Examples/Stereo/stereo_fixed_replay'
call('reject-plain-probes',[str(binary),'missing','missing','missing','missing',str(a.output/'reject'),
                          'plain','1','--workload-diagnostics','1'],a.output,expected=2)
if 'workload diagnostics require instrument kind' not in (a.output/'reject-plain-probes.log').read_text():raise RuntimeError('Wrong rejection cause')
(a.output/'verification.json').write_text(json.dumps({'status':'passed','checks':checks},indent=2)+'\n')
