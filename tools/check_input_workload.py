"""Validate optional probes: all cost stays in effective service, never removed."""
import csv
from pathlib import Path
def read(path):
    with Path(path).open(newline='') as f:return [{k:int(v) for k,v in r.items() if k!='ids'} for r in csv.DictReader(f)]
def check_rows(events,workload):
    errors=[]
    if len(events)!=len(workload):return ['probe_row_count']
    for i,(e,w) in enumerate(zip(events,workload)):
        if w['k']!=e['k']:errors.append('probe_index:'+str(i))
        ready=max(e['release_ns'],events[i-1]['eB_ns']) if i else e['release_ns']
        if not ready<=w['probe_before_begin_ns']<=w['probe_before_end_ns']<=e['aT_ns']:errors.append('before_outside_gap:'+str(i))
        if not e['eT_ns']<=w['probe_after_begin_ns']<=w['probe_after_end_ns']<=e['aB_ns']:errors.append('after_outside_gap:'+str(i))
        if not 0<=w['process_cpu_before_T_ns']<=w['process_cpu_after_T_ns']:errors.append('cpu_order:'+str(i))
        for prefix in ['before','after']:
            if not 0<=w[prefix+'_nonnull_points']<=w[prefix+'_point_slots'] or w[prefix+'_keypoints']<0:errors.append('count_range:'+str(i))
        for name in ['voluntary','involuntary']:
            if w['coordinator_'+name+'_after']<w['coordinator_'+name+'_before']:errors.append('switch_order:'+str(i))
    return errors
def check(directory,enabled):
    d=Path(directory);p=d/'replay-workload.csv'
    if not enabled:return [] if not p.exists() else ['disabled_probe_produced_log']
    if not p.exists():return ['missing_workload_log']
    return check_rows(read(d/'replay-events.csv'),read(p))
