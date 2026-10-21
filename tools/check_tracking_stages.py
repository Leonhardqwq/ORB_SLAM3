"""Check optional stage accounting without subtracting its measurement cost."""
from pathlib import Path
from check_input_workload import read
STAGES=['extraction','stereo_match','initialization','pose_prediction','local_update','local_search','local_optimize','keyframe']
def check_rows(events,rows):
    errors=[]
    if len(events)!=len(rows):return ['tracking_row_count']
    for i,(e,r) in enumerate(zip(events,rows)):
        if (e['round'],e['k'])!=(r['round'],r['k']):errors.append(f'index:{i}')
        ready=max(e['release_ns'],events[i-1]['eB_ns']) if i else e['release_ns']
        if not ready<=r['context_begin_ns']<=r['context_end_ns']<=e['aT_ns']:errors.append(f'context_boundary:{i}')
        if not e['eT_ns']<=r['read_begin_ns']<=r['read_end_ns']<=e['aB_ns']:errors.append(f'read_boundary:{i}')
        if not 0<=r['before_nonnull_points']<=r['before_point_slots']:errors.append(f'count_range:{i}')
        if any(r[k]<0 for k in ['map_id','map_points','map_keyframes','before_keypoints']):errors.append(f'negative_count:{i}')
        if r['pending_reset'] not in (0,1):errors.append(f'reset_flag:{i}')
        intervals=[];total=0
        for name in STAGES:
            ns,b,en,n=(r[name+s] for s in ['_ns','_begin_ns','_end_ns','_calls'])
            if n==0:
                if (ns,b,en)!=(0,0,0):errors.append(f'stale_stage:{i}:{name}')
            elif n==1:
                if not e['aT_ns']<=b<=en<=e['eT_ns'] or ns!=en-b:errors.append(f'stage_boundary:{i}:{name}')
                intervals.append((b,en,name));total+=ns
            else:errors.append(f'unexpected_calls:{i}:{name}')
        intervals.sort()
        if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])):errors.append(f'stage_overlap:{i}')
        if total>e['eT_ns']-e['aT_ns']:errors.append(f'negative_remainder:{i}')
        if r['extraction_calls']!=1:errors.append(f'missing_extraction:{i}')
        # Initialization and early exits legitimately omit other stages.
    return errors
def check(directory,enabled):
    p=Path(directory)/'replay-tracking.csv'
    if not enabled:return [] if not p.exists() else ['disabled_tracking_log']
    if not p.exists():return ['missing_tracking_log']
    return check_rows(read(Path(directory)/'replay-events.csv'),read(p))
