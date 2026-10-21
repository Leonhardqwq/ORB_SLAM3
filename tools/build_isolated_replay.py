"""Linux/WSL: snapshot ORB sources and rebuild locally with existing dependencies.

No dependency download, cache rebuild, branch change, or in-place build. The
output directory must be new. Existing binary and dependency hashes are retained.
"""
import argparse,hashlib,json,shutil,subprocess,time
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['repository','dependencies','prefix','output']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--jobs',type=int,default=2)
    a=p.parse_args()
    if a.jobs<1:raise ValueError('jobs must be positive')
    a.repository=a.repository.resolve();a.dependencies=a.dependencies.resolve();a.output=a.output.resolve()
    deps=[a.dependencies/'Thirdparty/g2o/lib/libg2o.so',a.dependencies/'Thirdparty/DBoW2/lib/libDBoW2.so']
    protected={str(p):sha(p) for p in deps}
    a.output.mkdir(parents=True,exist_ok=False);src=a.output/'source';src.mkdir()
    for folder in ['src','include','Examples','Examples_old','tools']:
        shutil.copytree(a.repository/folder,src/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['CMakeLists.txt','LICENSE']:shutil.copy2(a.repository/name,src/name)
    for name in ['Thirdparty','Vocabulary']:
        (src/name).symlink_to((a.dependencies/name).resolve(),target_is_directory=True)
    record={'source':str(src),'protected':protected,'steps':[],
            'sources':{str(p.relative_to(src)):sha(p) for n in ['src','include'] for p in (src/n).rglob('*') if p.is_file()}}
    commands=[['cmake','-S',str(src),'-B',str(a.output/'build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
                '-DCMAKE_PREFIX_PATH='+str(a.prefix.resolve()),'-DORB_USE_PREBUILT_G2O=ON'],
              ['cmake','--build',str(a.output/'build'),'--target','stereo_fixed_replay','stereo_euroc','mono_euroc',
                'stereo_inertial_euroc','rgbd_tum','-j',str(a.jobs)]]
    for i,cmd in enumerate(commands):
        t=time.monotonic()
        with (a.output/f'build-{i}.log').open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
        record['steps'].append(dict(command=cmd,returncode=r.returncode,seconds=time.monotonic()-t))
        (a.output/'build.json').write_text(json.dumps(record,indent=2))
        if r.returncode:return r.returncode
    binary=src/'Examples/Stereo/stereo_fixed_replay'
    record['binary_sha256']=sha(binary);record['library_sha256']=sha(src/'lib/libORB_SLAM3.so')
    record['ldd']=subprocess.check_output(['ldd',str(binary)],text=True)
    assert str(src/'lib/libORB_SLAM3.so') in record['ldd'] and 'not found' not in record['ldd']
    assert all(sha(Path(p))==h for p,h in protected.items())
    (a.output/'build.json').write_text(json.dumps(record,indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())
