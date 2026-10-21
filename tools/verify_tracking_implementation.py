"""Build and execute timer/API tests with assertions enabled; then replay lifecycle checks."""
import argparse,json,shlex,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser()
for n in ['build','repository','output','data-root']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);src=a.build/'source';checks=[]
def call(label,cmd,cwd=None,expected=0):
    start=time.monotonic()
    with (a.output/(label+'.log')).open('w') as f:r=subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=240)
    checks.append(dict(label=label,command=cmd,returncode=r.returncode,passed=r.returncode==expected,seconds=time.monotonic()-start))
    (a.output/'verification.json').write_text(json.dumps(dict(checks=checks),indent=2))
    print(label,checks[-1]['passed'],flush=True)
    if r.returncode!=expected:raise RuntimeError((a.output/(label+'.log')).read_text()[-3500:])
call('python-tests',[sys.executable,'-B','-m','unittest','test_tracking_stages.py','test_input_workload.py','test_effective_events.py','test_contained_backend.py','test_backend_stages.py','test_routine_deferral.py'],a.repository/'tools')
call('contained-backend-fault-injection',[sys.executable,'-B',str(a.repository/'tools/test_contained_backend.py')])
call('timer-compile',['g++','-std=c++11','-O2','-pthread','-I'+str(a.repository/'include'),str(a.repository/'tools/test_tracking_timer.cc'),str(a.repository/'src/TrackingDiagnostics.cc'),'-o',str(a.output/'timer-test')])
call('timer-test',[str(a.output/'timer-test')])
call('projection-compile',['g++','-std=c++11','-O2','-I'+str(a.repository/'include'),str(a.repository/'tools/test_projection_budget.cc'),'-o',str(a.output/'projection-test')])
call('projection-test',[str(a.output/'projection-test')])
call('extraction-compile',['g++','-std=c++11','-O2','-I'+str(a.repository/'include'),str(a.repository/'tools/test_extraction_budget.cc'),'-o',str(a.output/'extraction-test')])
call('extraction-test',[str(a.output/'extraction-test')])
raw=subprocess.check_output(['ninja','-t','commands','stereo_fixed_replay'],cwd=a.build/'build',text=True).splitlines()
commands=[shlex.split(line) for line in raw]
cc=next(c for c in commands if '-c' in c and c[c.index('-c')+1].endswith('stereo_fixed_replay.cc'))
cc=cc[:];cc[cc.index('-c')+1]=str(a.repository/'tools/test_tracking_api.cc');cc[cc.index('-o')+1]=str(a.output/'api.o')
for opt in ['-MT','-MF']:
    if opt in cc:i=cc.index(opt);del cc[i:i+2]
cc=[v for v in cc if v not in ['-MD','-DNDEBUG']]
ld=next(c for c in commands if '-c' not in c and '-o' in c and c[c.index('-o')+1].endswith('/stereo_fixed_replay'))
# Ninja shell no-op separators surround the actual linker, never execute shell text.
ld=ld[:]
while ld and ld[0] in [':','&&']:ld.pop(0)
while ld and ld[-1] in [':','&&']:ld.pop()
assert '&&' not in ld and ';' not in ld
ld[ld.index('-o')+1]=str(a.output/'api-test')
oi=[i for i,v in enumerate(ld) if v.endswith('stereo_fixed_replay.cc.o')];assert len(oi)==1
ld[oi[0]]=str(a.output/'api.o')
call('api-compile',cc,a.build/'build');call('api-link',ld,a.build/'build')
config=(src/'Examples/Stereo/EuRoC.yaml').read_text()+'\nExecution.mode: "fixed_stereo"\nExecution.serialStereo: 0\nExecution.synchronousLoop: 1\n'
(a.output/'settings.yaml').write_text(config)
call('api-test',[str(a.output/'api-test'),str(src/'Vocabulary/ORBvoc.txt'),str(a.output/'settings.yaml')],a.output)
(a.output/'serial-settings.yaml').write_text(config.replace('Execution.serialStereo: 0','Execution.serialStereo: 1'))
call('serial-api-test',[str(a.output/'api-test'),str(src/'Vocabulary/ORBvoc.txt'),str(a.output/'serial-settings.yaml')],a.output)
observer_cc=cc[:];observer_cc[observer_cc.index('-c')+1]=str(a.repository/'tools/test_sim3_observers.cc');observer_cc[observer_cc.index('-o')+1]=str(a.output/'observer.o')
observer_ld=ld[:];observer_ld[observer_ld.index('-o')+1]=str(a.output/'observer-test');observer_ld[observer_ld.index(str(a.output/'api.o'))]=str(a.output/'observer.o')
call('observer-compile',observer_cc,a.build/'build');call('observer-link',observer_ld,a.build/'build')
call('observer-test',[str(a.output/'observer-test'),'8'],a.output)
life_cc=cc[:];life_cc[life_cc.index('-c')+1]=str(a.repository/'tools/test_backend_policy_lifecycle.cc');life_cc[life_cc.index('-o')+1]=str(a.output/'lifecycle.o')
life_ld=ld[:];life_ld[life_ld.index('-o')+1]=str(a.output/'lifecycle-test');life_ld[life_ld.index(str(a.output/'api.o'))]=str(a.output/'lifecycle.o')
call('backend-lifecycle-compile',life_cc,a.build/'build');call('backend-lifecycle-link',life_ld,a.build/'build')
call('backend-lifecycle-test',[str(a.output/'lifecycle-test'),str(src/'Vocabulary/ORBvoc.txt'),str(a.output/'settings.yaml'),str(a.data_root/'V1_01_easy'),str(src/'Examples/Stereo/EuRoC_TimeStamps/V101.txt')],a.output)
for mode,kind in [('fixed','selftest'),('native_default','native_selftest')]:
    cmd=[sys.executable,str(a.repository/'tools/run_fixed_replay.py'),'--source',str(src),'--data',str(a.data_root/'V1_01_easy'),
         '--output',str(a.output/kind),'--mode',mode,'--kind',kind,'--serial-stereo','0','--synchronous-loop','1' if mode=='fixed' else '0',
         '--frames','80','--init-limit','100','--preload-limit','201','--threads','1','--timeout','180']
    call(kind,cmd)
    r=json.loads((a.output/kind/'run.json').read_text())
    assert r['replay']['tracking_diagnostics']==0
    checks[-1]['self_checks']=r['replay']['self_checks']
call('reject-plain-tracking',[str(src/'Examples/Stereo/stereo_fixed_replay'),'missing','missing','missing','missing',str(a.output/'reject'),
     'plain','1','--tracking-diagnostics','1'],expected=2)
assert 'tracking diagnostics require instrument kind' in (a.output/'reject-plain-tracking.log').read_text()
for label,flags in [('reject-incomplete-backend',['--work-control','7','--keyframe-period','8','--backend-keyframes','4']),
    ('reject-native-backend',['--backend-keyframes','4','--backend-points','1200']),
    ('reject-small-backend',['--backend-keyframes','1','--backend-points','1200'])]:
    call(label,[str(src/'Examples/Stereo/stereo_fixed_replay'),'missing','missing','missing','missing',str(a.output/label),'instrument','1']+flags,expected=2)
    assert 'backend' in (a.output/(label+'.log')).read_text()
for label,flags in [
    ('reject-zero-gba',['--global-ba-iterations','0']),
    ('reject-excess-gba',['--global-ba-iterations','11']),
    ('reject-native-gba',['--global-ba-iterations','3'])]:
    call(label,[str(src/'Examples/Stereo/stereo_fixed_replay'),'missing','missing','missing','missing',str(a.output/label),'instrument','1']+flags,expected=2)
    assert 'global BA' in (a.output/(label+'.log')).read_text()
for label,flags in [
    ('reject-native-deferral',['--defer-routine-keyframes','1']),
    ('reject-invalid-deferral',['--defer-routine-keyframes','2'])]:
    call(label,[str(src/'Examples/Stereo/stereo_fixed_replay'),'missing','missing','missing','missing',str(a.output/label),'instrument','1']+flags,expected=2)
    assert 'routine deferral' in (a.output/(label+'.log')).read_text()
(a.output/'verification.json').write_text(json.dumps(dict(status='passed',checks=checks),indent=2)+'\n')
