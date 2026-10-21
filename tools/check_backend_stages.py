"""Validate optional backend stage measurements without removing their cost."""
from pathlib import Path
from check_input_workload import read
STAGES=['insert','cull_points','create_points','fuse','local_ba','cull_keyframes','loop']
def check(directory,keyframes=0,points=0,maintenance=0,global_iterations=None,fixed_keyframes=0):
    root=Path(directory);f=root/'replay-backend-stages.csv'
    if not f.exists():return ['missing_backend_stages']
    events=read(root/'replay-events.csv');rows=read(f);errors=[]
    if len(events)!=len(rows):return ['backend_stage_row_count']
    for i,(e,r) in enumerate(zip(events,rows)):
        if (e['round'],e['k'])!=(r['round'],r['k']):errors.append(f'backend_index:{i}')
        total=0;intervals=[]
        for name in STAGES:
            ns,b,en,n=(r[name+s] for s in ['_ns','_begin_ns','_end_ns','_calls'])
            if n==0:
                if (ns,b,en)!=(0,0,0):errors.append(f'stale_backend_stage:{i}:{name}')
            else:
                if not e['aB_ns']<=b<=en<=e['eB_ns'] or not 0<=ns<=en-b:
                    errors.append(f'backend_stage_boundary:{i}:{name}')
                if n==1 and ns!=en-b:errors.append(f'backend_stage_single_call:{i}:{name}')
                total+=ns;intervals.append((b,en,n))
        if total>e['eB_ns']-e['aB_ns']:errors.append(f'backend_negative_remainder:{i}')
        if intervals and all(z[2]==1 for z in intervals):
            intervals.sort()
            if any(x[1]>y[0] for x,y in zip(intervals,intervals[1:])):errors.append(f'backend_overlap:{i}')
        if r['loop_calls']!=1:errors.append(f'backend_loop_scope:{i}')
        if not 0<=r['ba_calls']<=r['local_ba_calls']:errors.append(f'backend_ba_calls:{i}')
        if keyframes and r['ba_keyframes_max']>keyframes:errors.append(f'backend_keyframe_cap:{i}')
        if points and r['ba_points_max']>points:errors.append(f'backend_point_cap:{i}')
        if fixed_keyframes:
            if not 0<=r.get('ba_anchor_rejects',-1)<=r['local_ba_calls']-r['ba_calls']:errors.append(f'backend_anchor_guard:{i}')
            fixed=r.get('ba_fixed_keyframes_max',-1);candidates=r.get('ba_fixed_candidates_max',-1)
            if not 0<=fixed<=min(fixed_keyframes,candidates):errors.append(f'backend_fixed_observer_cap:{i}')
            if not 0<=r.get('ba_dropped_points_max',-1)<=points:errors.append(f'backend_point_constraints:{i}')
            # At most two image residuals per point-camera pair (stereo/fisheye).
            if r['ba_edges_max']>2*points*(keyframes+fixed_keyframes):errors.append(f'backend_edge_cap:{i}')
        if maintenance:
            if not 0<=r.get('fuse_targets_max',-1)<=maintenance:errors.append(f'backend_fusion_cap:{i}')
            if not 0<=r.get('cull_selected_max',-1)<=min(maintenance,r.get('cull_candidates_max',-1)):errors.append(f'backend_cull_cap:{i}')
        if global_iterations is not None:
            calls=r.get('gba_calls',-1);requested=r.get('gba_requested_max',-1);actual=r.get('gba_actual_max',-1)
            ns=r.get('gba_optimization_ns',-1)
            if calls<0 or not 0<=actual<=requested<=global_iterations or r.get('gba_iteration_errors',-1)!=0:
                errors.append(f'global_ba_iterations:{i}')
            if calls>0 and requested!=global_iterations:errors.append(f'global_ba_requested:{i}')
            if not 0<=ns<=r['loop_ns']:errors.append(f'global_ba_time:{i}')
            if calls==0 and (requested or actual or ns):errors.append(f'global_ba_stale:{i}')
    return errors
