"""Descriptive analysis by process repeat; contiguous frames are not iid trials."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np


def write_csv(path, rows):
    if not rows: return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(rows)


def quantiles(x, prefix):
    if not len(x): return {}
    return {prefix+k:float(v) for k,v in zip(['mean','p50','p90','p95','p99','max'],
            [np.mean(x),*np.percentile(x,[50,90,95,99]),np.max(x)])}


def streaks(fail):
    padded=np.r_[False,fail,False].astype(int)
    starts=np.where(np.diff(padded)==1)[0]; ends=np.where(np.diff(padded)==-1)[0]
    return ends-starts


def win_rate(success,h):
    if len(success)<h: return float('nan')
    counts=np.r_[0,np.cumsum(~success)]
    return float(np.mean(counts[h:]-counts[:-h]==0))


def rigid_align(est,gt):
    x=est-est.mean(0); y=gt-gt.mean(0)
    u,_,vt=np.linalg.svd(x.T@y)
    adjust=np.eye(3); adjust[-1,-1]=np.linalg.det(u@vt)
    rot=u@adjust@vt
    return x@rot+gt.mean(0)


def quality(a, gt):
    n=len(a); matrices=np.stack([a[f'pose{i}'] for i in range(12)],axis=1).reshape(n,3,4)
    good=(a['state']==2)&np.isfinite(matrices).all((1,2))
    # A return to initialization after tracking was established is a map epoch boundary.
    epochs=np.zeros(n,dtype=int); epoch=0; initialized=False; in_reset=False
    for i,state in enumerate(a['state']):
        if state==2: initialized=True; in_reset=False
        elif state<=1 and initialized and not in_reset:
            epoch+=1; in_reset=True
        epochs[i]=epoch
    parts=[]; all_errors=[]; trans=[]; angles=[]
    for seg in np.unique(epochs):
        ids=np.where(good & (epochs==seg))[0]
        if len(ids)<3:
            parts.append(dict(segment=int(seg),valid_frames=len(ids),ate_rmse_m=None)); continue
        errors=np.linalg.norm(rigid_align(matrices[ids,:,3],gt[ids,:,3])-gt[ids,:,3],axis=1)
        all_errors.extend(errors.tolist())
        parts.append(dict(segment=int(seg),valid_frames=len(ids),ate_rmse_m=float(np.sqrt(np.mean(errors**2)))))
        for i in ids:
            j=np.searchsorted(a['dataset_s'],a['dataset_s'][i]+1.)
            if j>=n or not good[j] or epochs[j]!=seg or abs(a['dataset_s'][j]-a['dataset_s'][i]-1)>0.11: continue
            er=matrices[i,:,:3].T@matrices[j,:,:3]
            et=matrices[i,:,:3].T@(matrices[j,:,3]-matrices[i,:,3])
            gr=gt[i,:,:3].T@gt[j,:,:3]
            gtrans=gt[i,:,:3].T@(gt[j,:,3]-gt[i,:,3])
            trans.append(float(np.linalg.norm(et-gtrans)))
            angles.append(float(np.degrees(np.arccos(np.clip((np.trace(gr.T@er)-1)/2,-1,1)))))
    return dict(valid_fraction=float(good.mean()),map_epoch_count=int(epochs.max()+1),
                whole_ate_rmse_m=float(np.sqrt(np.mean(np.square(all_errors)))) if epoch==0 and all_errors else None,
                segment_weighted_ate_rmse_m=float(np.sqrt(np.mean(np.square(all_errors)))) if all_errors else None,
                rpe_1s_translation_rmse_m=float(np.sqrt(np.mean(np.square(trans)))) if trans else None,
                rpe_1s_rotation_rmse_deg=float(np.sqrt(np.mean(np.square(angles)))) if angles else None,
                rpe_pairs=len(trans),segments=parts)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--runs',type=Path,required=True)
    ap.add_argument('--additional-runs',type=Path,nargs='*',default=[],help='Recorded repair attempts, with failures retained in the original root')
    ap.add_argument('--data',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    frozen=json.loads((a.runs/'frozen.json').read_text()); protocol=frozen['protocol']
    summary=[]; windows=[]; distribution=[]; traces=[]; conditions=[]; quality_details={}; streak_rows=[]; incomplete=[]
    result_paths=[p for folder in [a.runs,*a.additional_runs] for p in sorted(folder.glob('*/result.json'))]
    for result_path in result_paths:
        run=result_path.parent; result=json.loads(result_path.read_text()); rid=run.parent.name+'/'+run.name
        base={k:result[k] for k in ['sequence','mode','repeat','observation','status']}; base['run']=rid
        row=dict(base,frames=result.get('frames',0),wall_seconds=result.get('wall_seconds'),
                 peak_sampled_rss_mib=result.get('peak_sampled_rss_mib'))
        if result['status']!='completed':
            log=(run/'process.log').read_text(errors='replace')
            reason='SO3 exponential received NaN; exact origin unresolved' if 'SO3::exp failed!' in log else ('Upstream Viewer float-type parsing error' if 'parameter must be a real number' in log else 'See retained process log')
            row.update(exit_code=result.get('exit_code'),failure_reason=reason)
            partial=dict(row,expected_frames=result.get('expected_frames'),interpretation='Retained prefix only; not a full-sequence latency or reliability estimate')
            if result.get('frames',0)>0:
                f=np.genfromtxt(run/'frames.csv',delimiter=',',names=True)
                partial.update(quantiles(1000*(f['track_end_s']-f['track_begin_s']),'prefix_call_ms_'))
                prefix_valid=(f['state']==2)&np.column_stack([np.isfinite(f[f'pose{j}']) for j in range(12)]).all(1)
                partial['prefix_valid_fraction']=float(prefix_valid.mean())
                partial['last_recorded_frame']=int(f['frame'][-1])
                partial['last_recorded_dataset_s']=float(f['dataset_s'][-1])
                if result['mode']=='periodic': partial.update(quantiles(1000*(f['track_end_s']-f['release_s']),'prefix_delay_ms_'))
                if result['repeat']==1:
                    planned_end=float((a.data/'sequences'/result['sequence']/'times.txt').read_text().splitlines()[-1])
                    for i in range(len(f)):
                        traces.append(dict(sequence=result['sequence'],mode=result['mode'],frame=int(f['frame'][i]),
                            dataset_s=float(f['dataset_s'][i]),call_ms=float(1000*(f['track_end_s'][i]-f['track_begin_s'][i])),
                            service_ms=float(1000*(f['track_end_s'][i]-f['read_begin_s'][i])),
                            wait_ms=float(1000*(f['read_begin_s'][i]-f['release_s'][i])) if result['mode']=='periodic' else None,
                            delay_ms=float(1000*(f['track_end_s'][i]-f['release_s'][i])) if result['mode']=='periodic' else None,
                            state=int(f['state'][i]),run_status=result['status'],planned_end_s=planned_end))
            incomplete.append(partial)
            summary.append(row); continue
        resources=np.genfromtxt(run/'resources.csv',delimiter=',',names=True)
        if resources.size>1:
            cpu=np.diff(resources['process_cpu_s'])/np.diff(resources['wall_s'])
            row['cpu_mean_cores']=float(resources['process_cpu_s'][-1]/resources['wall_s'][-1])
            row['cpu_peak_sampled_cores']=float(cpu.max())
            row['host_load1_median']=float(np.median(resources['host_load1']))
        log=(run/'process.log').read_text(errors='replace')
        row['new_map_log_count']=log.count('Creation of new map with id:')
        f=np.genfromtxt(run/'frames.csv',delimiter=',',names=True)
        n=len(f)
        row['processing_wall_s']=result['runner']['processing_wall_s']
        row['dataset_duration_s']=float(f['dataset_s'][-1]-f['dataset_s'][0])
        row['last_read_begin_minus_nominal_s']=float(f['read_begin_s'][-1]-f['release_s'][-1])
        row['release_note']='Enforced periodic release' if result['mode']=='periodic' else 'Nominal reference only; upstream playback drift is not a queue-delay measurement'
        if (not np.array_equal(f['frame'],np.arange(n)) or np.any(np.diff(f['dataset_s'])<=0)
                or np.any(f['read_begin_s']>f['read_end_s']) or np.any(f['read_end_s']>f['track_begin_s'])
                or np.any(f['track_begin_s']>f['track_end_s'])):
            raise ValueError(f'Frame/timer ordering failed: {rid}')
        call=1000*(f['track_end_s']-f['track_begin_s'])
        read=1000*(f['read_end_s']-f['read_begin_s'])
        service=1000*(f['track_end_s']-f['read_begin_s'])
        wait=1000*(f['read_begin_s']-f['release_s'])
        delay=1000*(f['track_end_s']-f['release_s'])
        series=dict(call_ms=call,read_ms=read,service_ms=service)
        if result['mode']=='periodic':
            if np.min(wait)<-0.01: raise ValueError(f'Negative periodic waiting: {rid}')
            series.update(wait_ms=wait,delay_ms=delay)
        row.update(quantiles(f['probe_us'],'probe_us_'))
        row['csv_write_mean_us']=result['runner']['csv_write_total_us']/n
        row['timing_order_check']='passed'
        row['state_counts']=json.dumps({str(int(k)):int((f['state']==k).sum()) for k in np.unique(f['state'])})
        if result['observation']=='full':
            gt=np.loadtxt(a.data/'poses'/f'{result["sequence"]}.txt').reshape(-1,3,4)[:n]
            q=quality(f,gt); quality_details[rid]=q
            if row['new_map_log_count']>q['map_epoch_count']:
                q['whole_ate_rmse_m']=None
                q['segmentation_warning']='More new-map log events than observed state epochs; segment quality needs review'
            row.update({k:v for k,v in q.items() if k!='segments'})
        for name,values in series.items():
            row.update(quantiles(values,name+'_'))
            warm=f['dataset_s']-f['dataset_s'][0]<protocol['warmup_seconds']
            row.update(quantiles(values[warm],name+'_first10s_'))
            row.update(quantiles(values[~warm],name+'_after10s_'))
            for pct in np.unique(np.r_[np.linspace(0,99,100),99.5,99.9,100]):
                distribution.append(dict(base,metric=name,percentile=float(pct),value=float(np.percentile(values,pct))))
            for state in np.unique(f['state']):
                chosen=values[f['state']==state]
                conditions.append(dict(base,metric=name,state=int(state),n=len(chosen),**quantiles(chosen,'')))
        if result['mode']=='periodic':
            for deadline in protocol['deadlines_ms']:
                success=delay<=deadline
                valid=(f['state']==2)&np.column_stack([np.isfinite(f[f'pose{j}']) for j in range(12)]).all(1)
                lengths=streaks(~success)
                row[f'miss_rate_{deadline}ms']=float((~success).mean())
                row[f'max_miss_streak_{deadline}ms']=int(lengths.max()) if len(lengths) else 0
                for length in lengths: streak_rows.append(dict(base,deadline_ms=deadline,length_frames=int(length)))
                for h in protocol['windows']:
                    windows.append(dict(base,deadline_ms=deadline,H=h,windows=n-h+1,
                        timely_rate=win_rate(success,h),timely_valid_rate=win_rate(success&valid,h),
                        marginal_power=float(success.mean()**h),
                        independence_gap=win_rate(success,h)-float(success.mean()**h)))
        if result['repeat']==1:
            # Every frame, compact CSV for the preselected first replicate of each condition.
            for i in range(n):
                traces.append(dict(sequence=result['sequence'],mode=result['mode'],frame=i,
                    dataset_s=float(f['dataset_s'][i]),call_ms=float(call[i]),service_ms=float(service[i]),
                    wait_ms=float(wait[i]) if result['mode']=='periodic' else None,
                    delay_ms=float(delay[i]) if result['mode']=='periodic' else None,state=int(f['state'][i]),
                    run_status='completed',planned_end_s=float(f['dataset_s'][-1])))
        summary.append(row)
    write_csv(a.output/'runs.csv',summary)
    write_csv(a.output/'incomplete-runs.csv',incomplete)
    write_csv(a.output/'windows.csv',windows)
    write_csv(a.output/'distributions.csv',distribution)
    write_csv(a.output/'state-strata.csv',conditions)
    write_csv(a.output/'first-repeat-traces.csv',traces)
    write_csv(a.output/'miss-streaks.csv',streak_rows)
    (a.output/'quality-details.json').write_text(json.dumps(quality_details,indent=2)+'\n')
    grouped=[]
    for mode in protocol['playback_modes']:
        for seq in protocol['sequences']:
            rows=[r for r in summary if r['mode']==mode and r['sequence']==seq]
            complete=[r for r in rows if r['status']=='completed']
            setup_errors=sum(r.get('failure_reason')=='Upstream Viewer float-type parsing error' for r in rows)
            group=dict(mode=mode,sequence=seq,planned_repeats=protocol['repetitions'],attempts=len(rows),completed=len(complete),
                       setup_error_attempts=setup_errors,runtime_error_attempts=len(rows)-len(complete)-setup_errors)
            metrics=['call_ms_p50','call_ms_p99','call_ms_max','read_ms_mean','service_ms_p99','delay_ms_p95','delay_ms_p99','delay_ms_max',
                     'valid_fraction','whole_ate_rmse_m','miss_rate_100ms','miss_rate_200ms','miss_rate_500ms',
                     'max_miss_streak_100ms','max_miss_streak_200ms','max_miss_streak_500ms','peak_sampled_rss_mib',
                     'wait_ms_p99','wait_ms_max','cpu_mean_cores','last_read_begin_minus_nominal_s']
            for metric in metrics:
                vals=[r[metric] for r in complete if metric in r and r[metric] is not None]
                if vals: group[metric]={'median':float(np.median(vals)),'min':float(min(vals)),'max':float(max(vals)),'n':len(vals)}
            grouped.append(group)
    table=[]
    for g in grouped:
        r={k:v for k,v in g.items() if not isinstance(v,dict)}
        for metric in ['call_ms_p50','call_ms_p99','delay_ms_p99','whole_ate_rmse_m','valid_fraction','cpu_mean_cores','last_read_begin_minus_nominal_s']:
            if metric in g:
                for stat in ['median','min','max']: r[metric+'_'+stat]=g[metric][stat]
        for metric in ['delay_ms_max','wait_ms_max','peak_sampled_rss_mib','miss_rate_100ms']:
            if metric in g: r[metric+'_across_completed']=g[metric]['max']
        table.append(r)
    write_csv(a.output/'main-table.csv',table)
    (a.output/'summary.json').write_text(json.dumps(dict(groups=grouped,
        interpretation='Repeated process runs of three fixed scenes; frames/windows are dependent; ranges are descriptive. Main latency and window statistics condition on completed runs; incomplete prefixes and process completion are reported separately.',
        completed=sum(r['status']=='completed' for r in summary),attempts=len(summary)),indent=2)+'\n')
    print(json.dumps(grouped,indent=2))


if __name__=='__main__': main()
