"""Check actual deferral flags against preserved protection branches and effects."""
from pathlib import Path
from check_input_workload import read
def check(directory,enabled):
    root=Path(directory);trace=read(root/'replay-tracking.csv')
    events={r['round']:r for r in read(root/'replay-events.csv')};errors=[]
    for r in trace:
        if not r['keyframe_flags']&512:continue
        e=events.get(r['round']);f=r['keyframe_flags']
        if not enabled:errors.append('routine_deferral_leaked')
        if r['work_mode']==0 or r['match_inliers']<75 or f&(1|4|32|256) or not f&2 or not f&64:
            errors.append('routine_deferral_guard')
        if e is None or e['state']!=2 or e['keyframes']!=0:errors.append('routine_deferral_effect')
    return errors
