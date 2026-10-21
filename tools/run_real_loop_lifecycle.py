"""Replay real images until a loop/GBA has occurred, then test reset and shutdown.

Deliberately not a timing/quality experiment. Run only after timed runs have exited.
"""
import argparse,hashlib,json,os,signal,subprocess,time,shlex
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['build-record','data','settings','output']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--frames',type=int,default=1600)
    a=p.parse_args();build=json.loads(a.build_record.read_text());a.output.mkdir(parents=True,exist_ok=False)
    commands=[x['command'] for x in build['steps'] if 'command' in x]
    if not any('-c' in c for c in commands):
        lines=subprocess.check_output(['ninja','-C',str(a.build_record.parent/'build'),'-t','commands','stereo_fixed_replay'],text=True).splitlines()
        commands=[]
        for line in lines:
            c=shlex.split(line)
            if c[:2]==[':', '&&']:c=c[2:]
            if c[-2:]==['&&', ':']:c=c[:-2]
            if '&&' in c:raise ValueError('unsupported compound build recipe')
            commands.append(c)
    cc=next(list(c) for c in commands if '-c' in c)
    link=next(list(c) for c in commands if '-c' not in c and any(x.endswith('/stereo_fixed_replay') for x in c))
    binary=Path(link[link.index('-o')+1]);source=binary.parents[2]
    test=Path(__file__).resolve().parent/'test_fixed_loop_lifecycle.cc'
    cc[cc.index('-c')+1]=str(test);cc[cc.index('-o')+1]=str(a.output/'test.o')
    if '-MF' in cc:cc[cc.index('-MF')+1]=str(a.output/'test.d')
    link=[str(a.output/'test.o') if x.endswith('stereo_fixed_replay.cc.o') else x for x in link]
    link[link.index('-o')+1]=str(a.output/'test')
    results={'purpose':'real loop followed by reset/close; not a quality or timing comparison',
        'library_sha256':sha(source/'lib/libORB_SLAM3.so'),'test_source_sha256':sha(test),
        'settings_sha256':sha(a.settings),'steps':[]}
    for name,cmd in [('compile',cc),('link',link)]:
        with (a.output/(name+'.log')).open('w') as f:r=subprocess.run(cmd,cwd=a.build_record.parent/'build',stdout=f,stderr=subprocess.STDOUT)
        results['steps'].append(dict(name=name,command=cmd,returncode=r.returncode))
        if r.returncode:raise RuntimeError('See '+str(a.output/(name+'.log')))
    for reset in ['active','full']:
        cmd=[str(a.output/'test'),str(source/'Vocabulary/ORBvoc.txt'),str(a.settings),str(a.data),
             str(source/'Examples/Stereo/EuRoC_TimeStamps/V102.txt'),str(a.frames),reset]
        t=time.monotonic()
        with (a.output/(reset+'.log')).open('w') as log:
            child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,cwd=a.output,start_new_session=True)
            try:rc=child.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL);rc=child.wait()
        text=(a.output/(reset+'.log')).read_text(errors='replace')
        passed=rc==0 and 'REAL_LOOP_LIFECYCLE_PASSED' in text and 'BEFORE_RESET corrections=' in text
        results['steps'].append(dict(name=reset,command=cmd,returncode=rc,passed=passed,seconds=time.monotonic()-t,
            evidence=[s for s in text.splitlines() if 'BEFORE_RESET' in s or 'LIFECYCLE' in s]))
        (a.output/'results.json').write_text(json.dumps(results,indent=2))
        print(reset,passed,results['steps'][-1]['evidence'],flush=True)
        if not passed:return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
