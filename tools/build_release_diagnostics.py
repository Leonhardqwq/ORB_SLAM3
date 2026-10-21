"""Build only the replay against an existing Ninja build; keep that build read-only."""
import argparse, hashlib, json, shlex, shutil, subprocess, time
from pathlib import Path

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['existing-work','output','driver']: p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args(); old=a.existing_work.resolve(); out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False); src=out/'source'; stereo=src/'Examples/Stereo'; stereo.mkdir(parents=True)
    baseline=old/'source'
    for name in ['src','include','Thirdparty','Vocabulary','CMakeLists.txt']:
        (src/name).symlink_to(baseline/name,target_is_directory=(baseline/name).is_dir())
    for name in ['EuRoC.yaml','EuRoC_TimeStamps']:
        (stereo/name).symlink_to(baseline/'Examples/Stereo'/name,target_is_directory=(baseline/'Examples/Stereo'/name).is_dir())
    driver=stereo/'stereo_fixed_replay.cc'; shutil.copyfile(a.driver,driver)
    lines=subprocess.check_output(['ninja','-C',str(old/'build'),'-t','commands','stereo_fixed_replay'],text=True).splitlines()
    lines=[x for x in lines if 'Examples/Stereo/stereo_fixed_replay' in x]
    assert len(lines)==2, 'expected one compiler and one linker recipe'
    cc=shlex.split(lines[0]); original=str(baseline/'Examples/Stereo/stereo_fixed_replay.cc')
    oldobj=cc[cc.index('-o')+1]; obj=out/'replay.o'; binary=stereo/'stereo_fixed_replay'
    cc[cc.index('-o')+1]=str(obj); cc[cc.index(original)]=str(driver)
    for opt in ['-MT','-MF']:
        i=cc.index(opt); del cc[i:i+2]
    cc.remove('-MD')
    line=lines[1]; assert line.startswith(': && ') and line.endswith(' && :')
    ld=shlex.split(line[5:-5]); ld[ld.index(oldobj)]=str(obj); ld[ld.index('-o')+1]=str(binary)
    assert all(x not in ['&&',';','|'] for x in cc+ld)
    dependencies={str(f):sha(f) for f in (baseline/'include').rglob('*') if f.is_file()}
    dependencies.update({str(f):sha(f) for f in (baseline/'src').rglob('*') if f.is_file()})
    dependencies.update({str(f):sha(f) for f in [baseline/'lib/libORB_SLAM3.so',baseline/'Examples/Stereo/stereo_fixed_replay']})
    records=[]
    for name,cmd in [('compile',cc),('link',ld)]:
        start=time.monotonic()
        with (out/(name+'.log')).open('wb') as log:
            result=subprocess.run(cmd,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        records.append({'command':cmd,'returncode':result.returncode,'seconds':time.monotonic()-start})
        if result.returncode: print((out/(name+'.log')).read_text()[-5000:]); return result.returncode
    assert all(sha(Path(f))==h for f,h in dependencies.items())
    manifest={'driver_sha256':sha(driver),'binary_sha256':sha(binary),'existing_inputs':dependencies,'commands':records}
    (out/'build.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'built':str(binary),'sha256':sha(binary),'protected_inputs':len(dependencies)}))
    return 0

if __name__=='__main__': raise SystemExit(main())
