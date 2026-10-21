"""Run frozen, serial, three-arm tracking/workload/off diagnostics on existing sequences."""
import argparse,csv,hashlib,json,statistics,subprocess,sys
from pathlib import Path
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['source','repository','data-root','output','protocol','reference']:p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();sys.path.insert(0,str(a.repository/'tools'))
    from check_effective_events import audit
    from check_input_workload import check
    from check_tracking_stages import check as check_stages
    from score_online_trajectory import score
    cfg=json.loads(a.protocol.read_text(encoding='utf-8'))
    for folder in ['src','include']:
        for f in (a.repository/folder).rglob('*'):
            if f.is_file() and sha(f)!=sha(a.source/f.relative_to(a.repository)):raise ValueError('Core source differs: '+str(f))
    driver='Examples/Stereo/stereo_fixed_replay.cc'
    if sha(a.repository/driver)!=sha(a.source/driver):raise ValueError('Replay source mismatch')
    a.output.mkdir(parents=True,exist_ok=False)
    result={'protocol':cfg,'protocol_sha256':sha(a.protocol),'runner_sha256':sha(__file__),'runs':[],'status':'running',
            'input_mode_candidates':'frozen in input-mode protocol; no candidate refitting on this campaign'}
    result['source_hashes']={str(f.relative_to(a.repository)):sha(f) for folder in ['src','include'] for f in (a.repository/folder).rglob('*') if f.is_file()}
    result['driver_sha256']=sha(a.repository/driver)
    result['tools_sha256']={name:sha(a.repository/'tools'/name) for name in ['run_fixed_replay.py','check_input_workload.py','check_tracking_stages.py','check_effective_events.py','check_contained_backend.py','score_online_trajectory.py']}
    for entry in cfg['schedule']:
        seq=entry['sequence'];out=a.output/entry['id'];ts=a.source/'Examples/Stereo/EuRoC_TimeStamps'/('V101.txt' if seq=='V1_01_easy' else 'V102.txt')
        cmd=[sys.executable,str(a.repository/'tools/run_fixed_replay.py'),'--source',str(a.source),'--data',str(a.data_root/seq),
             '--output',str(out),'--mode','fixed','--serial-stereo','0','--synchronous-loop','1','--kind','instrument',
             '--workload-diagnostics',str(entry['workload']),'--tracking-diagnostics',str(entry['tracking']),'--frames',str(cfg['evaluation_frames']),'--offset','0',
             '--init-limit','100','--preload-limit','1701','--period-ns',str(cfg['h_ns']),'--threads','1','--spin-us','0',
             '--timeout','240','--settings',str(a.source/'Examples/Stereo/EuRoC.yaml'),'--timestamps',str(ts)]
        print('START '+entry['id'],flush=True)
        with (a.output/(entry['id']+'.log')).open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
        rec=dict(entry,command=cmd,path=str(out),returncode=r.returncode)
        result['runs'].append(rec)
        if r.returncode:
            result['status']='acquisition_error';dump(a.output/'results.json',result);return 1
        run=json.loads((out/'run.json').read_text());summary=run['replay']
        if summary['workload_diagnostics']!=entry['workload']:raise ValueError('Wrong probe flag')
        account,detail=audit(out,dict(cfg,thread_policy='joined_stereo',synchronous_loop=True),a.reference)
        if summary['tracking_diagnostics']!=entry['tracking']:raise ValueError('Wrong tracking flag')
        errors=check(out,entry['workload'])+check_stages(out,entry['tracking'])
        rec.update(run_sha256=sha(out/'run.json'),binary_sha256=run['binary_sha256'],library=run['loaded_library'],
                   wall_ns=summary['evaluation_elapsed_ns'],cpu_ns=summary['evaluation_cpu_ns'],RSS_bytes=run['sampled_peak_RSS_bytes'],
                   invalid_pose_frames=summary['invalid_pose_frames'],accounting=account,probe_errors=errors,
                   quality=score(out/'replay-online.csv',a.data_root/seq,20,cfg['evaluation_frames']))
        dump(out/'accounting.json',account)
        if detail:
            with (out/'durations.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(detail[0]));w.writeheader();w.writerows(detail)
        rec['accepted_for_diagnosis']=account['status']=='accounting_passed' and not errors
        # Preserve clock/measurement failures without pretending they pass.
        # Remaining runs are independent collection/diagnosis, not E5/E6.
        dump(a.output/'results.json',result)
        print(json.dumps({k:rec[k] for k in ['id','wall_ns','cpu_ns','invalid_pose_frames','accepted_for_diagnosis']}),flush=True)
    result['overhead']={}
    for seq in cfg['sequences']:
        subset=[r for r in result['runs'] if r['sequence']==seq]
        result['overhead'][seq]={}
        for arm in ['workload','stages']:
            ratio={}
            for metric in ['wall_ns','cpu_ns','RSS_bytes']:
                ratio[metric+'_median_ratio']=statistics.median([r[metric] for r in subset if r['arm']==arm])/statistics.median([r[metric] for r in subset if r['arm']=='off'])
            ratio['wall_gate']=ratio['wall_ns_median_ratio']<=cfg['wall_ratio_limit']
            ratio['paired']=[dict(block=b,wall_ratio=next(r['wall_ns'] for r in subset if r['arm']==arm and r['block']==b)/next(r['wall_ns'] for r in subset if r['arm']=='off' and r['block']==b),
                cpu_ratio=next(r['cpu_ns'] for r in subset if r['arm']==arm and r['block']==b)/next(r['cpu_ns'] for r in subset if r['arm']=='off' and r['block']==b),
                ATE_difference_m=next(r['quality']['ATE_RMSE_m'] for r in subset if r['arm']==arm and r['block']==b)-next(r['quality']['ATE_RMSE_m'] for r in subset if r['arm']=='off' and r['block']==b)) for b in range(1,4)]
            result['overhead'][seq][arm]=ratio
    result['status']='completed_diagnostic_collection'
    result['measurement_gate']=all(r['accepted_for_diagnosis'] for r in result['runs']) and all(r['wall_gate'] for seq in result['overhead'].values() for r in seq.values())
    result['E4_accepted']=False;result['E5']='not_entered';result['E6']='not_entered'
    dump(a.output/'results.json',result)
    print(json.dumps({'status':result['status'],'measurement_gate':result['measurement_gate'],'overhead':result['overhead']},indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())
