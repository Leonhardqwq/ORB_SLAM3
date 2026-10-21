"""Serial blocked intervention study. All runs, including poor quality, retained."""
import argparse,csv,hashlib,json,subprocess,sys
from pathlib import Path
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['source','repository','data-root','output','protocol','reference']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--comparison-build',type=Path)
    p.add_argument('--comparison-arm')
    p.add_argument('--resume-recording',action='store_true',help='Preserve and record existing completed runs, never rerun them')
    a=p.parse_args();sys.path.insert(0,str(a.repository/'tools'))
    if bool(a.comparison_build)!=bool(a.comparison_arm):raise ValueError('Comparison needs build and arm')
    from check_effective_events import audit
    from check_tracking_stages import check
    from score_online_trajectory import score
    cfg=json.loads(a.protocol.read_text(encoding='utf-8'))
    for folder in ['src','include']:
        for f in (a.repository/folder).rglob('*'):
            if f.is_file() and sha(f)!=sha(a.source/f.relative_to(a.repository)):raise ValueError('Core source differs: '+str(f))
    driver='Examples/Stereo/stereo_fixed_replay.cc'
    if sha(a.repository/driver)!=sha(a.source/driver):raise ValueError('Driver differs')
    comparison=None
    if a.comparison_build:
        record=json.loads((a.comparison_build/'build.json').read_text());comparison=a.comparison_build/'source'
        for rel,h in record['sources'].items():
            if sha(comparison/rel)!=h:raise ValueError('Historical comparison source changed')
        if sha(comparison/'Examples/Stereo/stereo_fixed_replay')!=record['binary_sha256'] or sha(comparison/'lib/libORB_SLAM3.so')!=record['library_sha256']:
            raise ValueError('Historical comparison binary changed')
        if a.comparison_arm not in cfg['arms']:raise ValueError('Unknown comparison arm')
    if a.resume_recording:
        original=a.output/'results.json'
        prior=json.loads(original.read_text())
        if prior['protocol_sha256']!=sha(a.protocol) or prior['status']!='running':
            raise ValueError('Only interrupted bookkeeping of the same planned campaign can resume')
        before=a.output/'before-recording-recovery.json'
        with before.open('x') as stream:stream.write(original.read_text())
        for rec in prior['runs']:
            if rec.get('run_sha256')!=sha(Path(rec['path'])/'run.json'):
                raise ValueError('Previously recorded raw run changed')
        if [r['id'] for r in prior['runs']]!=[e['id'] for e in cfg['schedule'][:len(prior['runs'])]]:
            raise ValueError('Completed schedule prefix differs')
    else:
        a.output.mkdir(parents=True,exist_ok=False)
    result={'status':'running','protocol':cfg,'protocol_sha256':sha(a.protocol),'runner_sha256':sha(__file__),'runs':[],
            'E4_accepted':False,'E5':'not_entered','E6':'not_entered'}
    if a.resume_recording:
        result=prior
        result['recording_recovery']=dict(original_sha256=sha(before),runner_sha256=sha(__file__),
            note='Existing completed processes never rerun; invalid measurement retained')
    done={r['id'] for r in result['runs']}
    for e in cfg['schedule']:
        if e['id'] in done:continue
        out=a.output/e['id'];seq=e['sequence']
        run_source=comparison if e['arm']==a.comparison_arm else a.source
        timestamp_names=cfg.get('timestamps',{'V1_01_easy':'V101.txt','V1_02_medium':'V102.txt'})
        if seq not in timestamp_names:raise ValueError('No explicitly configured timestamp file for '+seq)
        timestamp_name=timestamp_names[seq]
        if Path(timestamp_name).name!=timestamp_name:raise ValueError('Timestamp must be a simple filename')
        ts=run_source/'Examples/Stereo/EuRoC_TimeStamps'/timestamp_name
        if not ts.is_file():raise ValueError('Missing timestamp file: '+str(ts))
        cmd=[sys.executable,str(a.repository/'tools/run_fixed_replay.py'),'--source',str(run_source),'--data',str(a.data_root/seq),
             '--output',str(out),'--mode','fixed','--serial-stereo',str(cfg.get('serial_stereo',0)),'--synchronous-loop','1','--kind','instrument',
             '--tracking-diagnostics','1','--work-control',str(e['control']),'--policy-seed',str(e['seed']),
             '--frames',str(cfg['evaluation_frames']),'--offset','0','--init-limit','100','--preload-limit','1701',
             '--period-ns',str(cfg['h_ns']),'--threads','1','--timeout','240',
             '--settings',str(run_source/'Examples/Stereo/EuRoC.yaml'),'--timestamps',str(ts)]
        if cfg.get('cpu_affinity'):
            cmd+=['--cpu-affinity',','.join(map(str,cfg['cpu_affinity']))]
        if cfg.get('resource_diagnostics'):
            cmd+=['--resource-diagnostics','1']
        if e.get('defer_routine_keyframes'):cmd+=['--defer-routine-keyframes',str(e['defer_routine_keyframes'])]
        if e.get('global_ba_iterations'):cmd+=['--global-ba-iterations',str(e['global_ba_iterations'])]
        if e.get('backend_keyframes') or e.get('backend_points'):cmd+=['--backend-keyframes',str(e.get('backend_keyframes',0)),'--backend-points',str(e.get('backend_points',0))]
        if e.get('extraction_cell_candidates'):cmd+=['--extraction-cell-candidates',str(e['extraction_cell_candidates'])]
        if e.get('backend_fixed_keyframes'):cmd+=['--backend-fixed-keyframes',str(e['backend_fixed_keyframes'])]
        if e.get('maintenance_keyframes'):cmd+=['--maintenance-keyframes',str(e['maintenance_keyframes'])]
        if e.get('keyframe_period'):cmd+=['--keyframe-period',str(e['keyframe_period'])]
        print('START '+e['id'],flush=True)
        if out.exists():
            if not a.resume_recording or not (out/'run.json').exists():
                raise ValueError('Existing incomplete raw process cannot be silently replaced')
            existing=json.loads((out/'run.json').read_text())
            returncode=existing['returncode']
        else:
            with (a.output/(e['id']+'.log')).open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
            returncode=r.returncode
        rec=dict(e,command=cmd,path=str(out),returncode=returncode);result['runs'].append(rec)
        if returncode:
            result['status']='acquisition_error';dump(a.output/'results.json',result);return 1
        run=json.loads((out/'run.json').read_text());s=run['replay']
        account,rows=audit(out,dict(cfg,thread_policy=cfg.get('thread_policy','joined_stereo'),synchronous_loop=True),a.reference)
        errors=check(out,1)
        from check_routine_deferral import check as check_deferral
        errors+=check_deferral(out,bool(e.get('defer_routine_keyframes',0)))
        if s.get('defer_routine_keyframes',0)!=e.get('defer_routine_keyframes',0):errors.append('routine deferral policy mismatch')
        trace=list(csv.DictReader((out/'replay-tracking.csv').open()))
        # Reconstruct the complete precomputed tape, including initialization.
        rng=e['seed'];mode=0
        for t in trace:
            rng^=(rng<<13)&0xffffffff;rng^=rng>>17;rng^=(rng<<5)&0xffffffff
            if rng&15==0:mode=1-mode
            if int(t['work_control'])!=e['control']:errors.append('control mismatch')
            expected_mode=int(t['round'])%e['keyframe_period'] if e['control']>=6 else (0 if e['control']==5 else mode)
            if e['control'] and int(t['work_mode'])!=expected_mode:errors.append('mode tape mismatch')
            if e['control']>=5:
                requested=e['control']>=6 and expected_mode==0
                if int(t['keyframe_period'])!=e.get('keyframe_period',0) or bool(int(t['keyframe_request']))!=requested:
                    errors.append('scheduled request mismatch')
                if int(t['keyframe_flags'])&256 and (not requested or int(t['match_inliers'])<50):
                    errors.append('scheduled request guard mismatch')
            if e['control']>=2:
                k,p=(32,2400) if e['control']>=5 or mode else (16,1200)
                if int(t['keyframe_budget'])!=k or int(t['point_budget'])!=p:errors.append('budget mismatch')
                if int(t['local_keyframes'])>k or int(t['local_points'])>p:errors.append('cap exceeded')
                if 'ref_raw' in t:
                    raw,eligible,used=(int(t[n]) for n in ['ref_raw','ref_eligible','ref_used'])
                    if not 0<=eligible<=raw:errors.append('reference eligibility range')
                    if used!=(eligible if e['control']==3 or e['control']>=5 else raw):errors.append('reference rule mismatch')
                if 'projection_reference' in t:
                    ref=int(t['projection_reference']);skip=int(t['projection_matched_slots'])
                    if not 0<=ref<=int(t['local_points']) or skip<0:errors.append('projection count range')
                    if e['control']!=4 and (ref or skip):errors.append('projection policy leaked')
        from check_extraction_budget import check as check_extraction
        errors+=check_extraction(out,e.get('extraction_cell_candidates',0),cfg.get('serial_stereo',0)==1)
        backend_path=out/'replay-backend-stages.csv'
        if e['control']>=6 and cfg.get('backend_stage_diagnostics'):
            from check_backend_stages import check as check_backend
            bk=e.get('backend_keyframes',8) if e['control']==7 else 0
            bp=e.get('backend_points',2400) if e['control']==7 else 0
            errors+=check_backend(out,bk,bp,e.get('maintenance_keyframes',0),e.get('global_ba_iterations'),e.get('backend_fixed_keyframes',0))
            if s.get('backend_fixed_keyframes',0)!=e.get('backend_fixed_keyframes',0):errors.append('fixed observer policy mismatch')
            if s.get('global_ba_iterations',0)!=e.get('global_ba_iterations',0):errors.append('global BA policy mismatch')
            if s.get('backend_keyframes',bk)!=bk or s.get('backend_points',bp)!=bp:errors.append('backend policy mismatch')
            if s.get('maintenance_keyframes',0)!=e.get('maintenance_keyframes',0):errors.append('maintenance policy mismatch')
        if cfg.get('cpu_affinity') and run.get('requested_cpu_affinity')!=cfg['cpu_affinity']:
            errors.append('CPU affinity policy mismatch')
        if cfg.get('resource_diagnostics') and (not run.get('resource_diagnostics') or run['resource_diagnostics']['errors']):
            errors.append('resource diagnostics incomplete')
        rec.update(resource_diagnostics=run.get('resource_diagnostics'),resource_environment=run.get('resource_environment'),accounting=account,probe_errors=errors,accepted_for_diagnosis=account['status']=='accounting_passed' and not errors,
            run_sha256=sha(out/'run.json'),binary_sha256=run['binary_sha256'],library=run['loaded_library'],
            wall_ns=s['evaluation_elapsed_ns'],cpu_ns=s['evaluation_cpu_ns'],RSS_bytes=run['sampled_peak_RSS_bytes'],
            invalid_pose_frames=s['invalid_pose_frames'],quality=score(out/'replay-online.csv',a.data_root/seq,20,cfg['evaluation_frames']))
        # Preserve the failed audit and checkpoint even when it yields no rows.
        for name in ['accounting.json','durations.csv']:
            existing=out/name
            if a.resume_recording and existing.exists():
                with (out/(name+'.before-recording-recovery')).open('xb') as stream:
                    stream.write(existing.read_bytes())
        dump(out/'accounting.json',account)
        dump(a.output/'results.json',result)
        with (out/'durations.csv').open('w',newline='') as f:
            if rows:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        print(json.dumps(dict(id=e['id'],measurement=rec['accepted_for_diagnosis'],ATE=rec['quality']['ATE_RMSE_m'],invalid=s['invalid_pose_frames'])),flush=True)
    result['status']='completed_intervention_collection'
    result['measurement_gate']=all(r['accepted_for_diagnosis'] for r in result['runs'])
    dump(a.output/'results.json',result);return 0
if __name__=='__main__':raise SystemExit(main())
