"""Serial measurement revalidation; performance outcomes never gate model diagnosis."""
import argparse,csv,hashlib,json,re,statistics,subprocess,sys
from pathlib import Path

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x): Path(p).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['source','authoritative-source','data-root','output','protocol','reference','tools']:
        p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();sys.path.insert(0,str(a.tools))
    from check_effective_events import audit
    from run_effective_collection import sequence_inputs
    from score_online_trajectory import score
    cfg=json.loads(a.protocol.read_text(encoding='utf-8'))
    a.output.mkdir(parents=True,exist_ok=False)
    files=list(a.source.glob('src/*.cc'))+list(a.source.glob('include/*.h'))
    files += [a.source/'CMakeLists.txt',a.source/'Examples/Stereo/stereo_fixed_replay.cc']
    for f in files:
        if sha(f)!=sha(a.authoritative_source/f.relative_to(a.source)):
            raise ValueError('Source mismatch: '+str(f))
    binary=a.source/'Examples/Stereo/stereo_fixed_replay'
    deps=subprocess.check_output(['ldd',str(binary)],text=True)
    match=re.search(r'libORB_SLAM3.so => (\S+)',deps)
    if not match or 'not found' in deps:raise ValueError('Unresolved library')
    lib=Path(match[1]).resolve()
    snapshot={'source':{str(f.relative_to(a.source)):sha(f) for f in files},
        'binary':str(binary),'binary_sha256':sha(binary),'library':str(lib),'library_sha256':sha(lib),
        'protocol_sha256':sha(a.protocol),'runner_sha256':sha(Path(__file__)),
        'reference_sha256':sha(a.reference),'python':sys.version,
        'tools':{f.name:sha(f) for f in a.tools.glob('*.py')},'sequences':{}}
    inputs={}
    for seq in cfg['sequences']:
        c=dict(cfg,**cfg['sequences'][seq],sequence=seq)
        ts,st,images=sequence_inputs(a.source,a.data_root/seq,c)
        inputs[seq]=(ts,st,c)
        snapshot['sequences'][seq]={'images':images,'timestamps':sha(ts),'settings':sha(st),
            'ground_truth':sha(a.data_root/seq/'mav0/state_groundtruth_estimate0/data.csv')}
    dump(a.output/'inputs.json',snapshot)
    result={'protocol':cfg,'protocol_sha256':sha(a.protocol),'inputs_sha256':sha(a.output/'inputs.json'),
        'runs':[],'E2':'running','data_gate':'pending','E4':'not_started',
        'performance_acceptance':'separate; previous failures retained'}
    dump(a.output/'results.json',result)
    for entry in cfg['schedule']:
        if entry['role']=='cross_sequence' and result['E2']!='passed':
            result['data_gate']='blocked_by_E2';break
        seq=entry['sequence'];ts,st,c=inputs[seq];out=a.output/entry['id']
        cmd=[sys.executable,str(a.tools/'run_fixed_replay.py'),'--source',str(a.source),
            '--data',str(a.data_root/seq),'--output',str(out),'--mode','fixed',
            '--serial-stereo','0','--synchronous-loop','1','--kind',entry['kind'],
            '--frames',str(c['evaluation_frames']),'--offset','0','--init-limit','100',
            '--preload-limit',str(c['preload_limit']),'--period-ns',str(cfg['h_ns']),
            '--threads','1','--spin-us','0','--timeout',str(cfg['timeout_seconds']),
            '--settings',str(st),'--timestamps',str(ts)]
        print('START '+entry['id'],flush=True)
        with (a.output/(entry['id']+'.log')).open('w') as log:
            proc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
        run=json.loads((out/'run.json').read_text())
        rec=dict(entry,path=str(out),returncode=proc.returncode,run_sha256=sha(out/'run.json'),command=cmd)
        result['runs'].append(rec)
        if proc.returncode or not run['accepted']:
            rec['status']='acquisition_error';result['data_gate']='failed';dump(a.output/'results.json',result);return 1
        if run['binary_sha256']!=snapshot['binary_sha256'] or run['loaded_library']['sha256']!=snapshot['library_sha256']:
            raise ValueError('Runtime hash mismatch')
        s=run['replay'];rec.update(wall_ns=s['evaluation_elapsed_ns'],cpu_ns=s['evaluation_cpu_ns'],
            RSS_bytes=run['sampled_peak_RSS_bytes'],invalid_pose_frames=s['invalid_pose_frames'],
            status='completed',quality=score(out/'replay-online.csv',a.data_root/seq,20,c['evaluation_frames']))
        if entry['kind']=='instrument':
            contract=dict(c,thread_policy='joined_stereo',synchronous_loop=True)
            account,detail=audit(out,contract,a.reference)
            dump(out/'accounting.json',account)
            if detail:
                with (out/'durations.csv').open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(detail[0]));w.writeheader();w.writerows(detail)
            rec['accounting']={k:v for k,v in account.items() if k!='windows'}
            if account['status']!='accounting_passed':
                result['data_gate']='failed';dump(a.output/'results.json',result);return 1
        e2=[r for r in result['runs'] if r['role']=='measurement']
        if len(e2)==6:
            wall={k:[r['wall_ns'] for r in e2 if r['kind']==k] for k in ['instrument','plain']}
            cpu={k:[r['cpu_ns'] for r in e2 if r['kind']==k] for k in ['instrument','plain']}
            ratio=statistics.median(wall['instrument'])/statistics.median(wall['plain'])
            result['overhead']={'wall_median_ratio':ratio,'cpu_median_ratio':statistics.median(cpu['instrument'])/statistics.median(cpu['plain']),
                'wall_ns':wall,'cpu_ns':cpu,'wall_limit':cfg['wall_ratio_limit'],
                'meaning':'Waiting-inclusive observed overhead, not a per-call timing uncertainty bound'}
            result['E2']='passed' if ratio<=cfg['wall_ratio_limit'] else 'failed'
        dump(a.output/'results.json',result)
        print(json.dumps({k:rec[k] for k in ['id','status','wall_ns','cpu_ns','invalid_pose_frames']}),flush=True)
    if result['E2']=='passed' and len(result['runs'])==len(cfg['schedule']):
        result['data_gate']='passed_for_exploratory_probability_diagnosis'
        result['E4']='ready_for_diagnostics; not_validated'
    result['protected_binary_unchanged']=sha(binary)==snapshot['binary_sha256'] and sha(lib)==snapshot['library_sha256']
    dump(a.output/'results.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['runs','protocol']},indent=2),flush=True)
    return 0 if result['E2']=='passed' and result['data_gate'].startswith('passed') else 1
if __name__=='__main__':raise SystemExit(main())
