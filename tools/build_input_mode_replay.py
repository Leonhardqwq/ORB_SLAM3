"""Rebuild only replay from an incremental build.json; baseline remains read-only."""
import argparse,hashlib,json,shutil,subprocess,time
from pathlib import Path
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['existing-work','output','driver']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();old=a.existing_work.resolve();out=a.output.resolve();base=old/'source'
    commands=[r['command'] for r in json.loads((old/'build.json').read_text())['steps'] if 'command' in r]
    compile_cmd=next(c[:] for c in commands if '-c' in c)
    links=[c[:] for c in commands if '-c' not in c and '-o' in c and c[c.index('-o')+1].endswith('/stereo_fixed_replay')]
    if len(links)!=1:raise ValueError('Expected one replay link command')
    out.mkdir(parents=True,exist_ok=False);src=out/'source';stereo=src/'Examples/Stereo';stereo.mkdir(parents=True)
    for name in ['src','include','Thirdparty','Vocabulary','CMakeLists.txt']:(src/name).symlink_to(base/name,target_is_directory=(base/name).is_dir())
    for name in ['EuRoC.yaml','EuRoC_TimeStamps']:(stereo/name).symlink_to(base/'Examples/Stereo'/name,target_is_directory=(base/'Examples/Stereo'/name).is_dir())
    driver=stereo/'stereo_fixed_replay.cc';shutil.copyfile(a.driver,driver)
    obj=out/'replay.o';binary=stereo/'stereo_fixed_replay'
    compile_cmd[compile_cmd.index('-c')+1]=str(driver)
    compile_cmd[compile_cmd.index('-o')+1]=str(obj)
    for opt in ['-MT','-MF']:
        if opt in compile_cmd:i=compile_cmd.index(opt);del compile_cmd[i:i+2]
    if '-MD' in compile_cmd:compile_cmd.remove('-MD')
    ld=links[0];ld[ld.index('-o')+1]=str(binary)
    oi=[i for i,x in enumerate(ld) if x.endswith('stereo_fixed_replay.cc.o')]
    if len(oi)!=1:raise ValueError('Expected one driver object')
    ld[oi[0]]=str(obj)
    protected={str(f):sha(f) for folder in ['src','include'] for f in (base/folder).rglob('*') if f.is_file()}
    for f in [base/'lib/libORB_SLAM3.so',base/'Examples/Stereo/stereo_fixed_replay',old/'build.json']:protected[str(f)]=sha(f)
    result={'baseline':str(old),'driver_sha256':sha(driver),'protected':protected,'commands':[]}
    for label,cmd in [('compile',compile_cmd),('link',ld)]:
        start=time.monotonic()
        with (out/(label+'.log')).open('w') as log:r=subprocess.run(cmd,cwd=old/'build',stdout=log,stderr=subprocess.STDOUT,timeout=180)
        result['commands'].append(dict(command=cmd,returncode=r.returncode,seconds=time.monotonic()-start))
        if r.returncode:print((out/(label+'.log')).read_text()[-5000:]);return r.returncode
    result['ldd']=subprocess.check_output(['ldd',str(binary)],text=True)
    if str(base/'lib/libORB_SLAM3.so') not in result['ldd'] or 'not found' in result['ldd']:raise ValueError('Library mismatch')
    if not all(sha(f)==h for f,h in protected.items()):raise ValueError('Protected inputs changed')
    result['binary_sha256']=sha(binary);result['builder_sha256']=sha(__file__)
    (out/'build.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'binary':str(binary),'sha256':sha(binary),'protected_inputs':len(protected)}))
    return 0
if __name__=='__main__':raise SystemExit(main())
