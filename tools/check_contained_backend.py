"""Boundary trace checks for explicitly joined stereo workers; not race certification."""
import csv

def check(directory, rows, run, contract):
    errors=[]
    if contract.get('thread_policy') not in ('joined_stereo','serial_contained'):
        return ['unknown_thread_policy']
    summary=run['replay']
    limit=3 if contract['thread_policy']=='joined_stereo' else 1
    if (summary['threads_at_evaluation_start']!=1 or summary['threads_at_evaluation_end']!=1
            or not 1<=run['sampled_peak_threads']<=limit):errors.append('unexpected_threads')
    with (directory/'replay-backend.csv').open(newline='') as f:
        backend=[{k:int(v) for k,v in r.items()} for r in csv.DictReader(f)]
    if len(backend)!=len(rows):return errors+['backend_length']
    names=['loop_processed','loop_corrected','maps_merged','gba_completed']
    prev={n:0 for n in names}
    for r,b in zip(rows,backend):
        if b['round']!=r['round'] or b['k']!=r['k']:errors.append('backend_index')
        if any(b[n]!=1 for n in ['threads_before_T','threads_after_T','threads_after_B']):
            errors.append('worker_at_boundary')
        if any(b[n]<prev[n] for n in names):errors.append('backend_counter_decreased')
        delta=b['loop_processed']-prev['loop_processed']
        if not 0<=delta<=r['keyframes']:errors.append('loop_work_crossed_round')
        if b['loop_corrected']+b['maps_merged']>b['loop_processed']:errors.append('correction_without_keyframe')
        if b['gba_completed']>b['loop_corrected']+b['maps_merged']:errors.append('gba_without_correction')
        if contract.get('synchronous_loop') is False and any(b[n] for n in names):errors.append('unexpected_loop_work')
        prev=b
    return sorted(set(errors))
