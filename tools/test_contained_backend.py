"""Reject background workers, lost/cross-round evidence and unjustified counters."""
import copy,csv,json,tempfile
from pathlib import Path
from check_contained_backend import check

def main():
    rows=[dict(round=0,k=-1,keyframes=1),dict(round=1,k=0,keyframes=1),dict(round=2,k=1,keyframes=0)]
    backend=[dict(round=i,k=i-1,threads_before_T=1,threads_after_T=1,threads_after_B=1,
                  loop_processed=int(i>0),loop_corrected=int(i>0),maps_merged=0,gba_completed=int(i>0)) for i in range(3)]
    run=dict(sampled_peak_threads=3,replay=dict(threads_at_evaluation_start=1,threads_at_evaluation_end=1))
    config=dict(thread_policy='joined_stereo',synchronous_loop=True)
    cases=[('joined_workers_complete',None,True),
        ('thread_escapes_T',lambda r,b,c:b[1].update(threads_after_T=2),False),
        ('thread_escapes_B',lambda r,b,c:b[1].update(threads_after_B=2),False),
        ('hidden_worker',lambda r,b,c:r.update(sampled_peak_threads=4),False),
        ('missing_boundary',lambda r,b,c:b.pop(),False),
        ('counter_goes_back',lambda r,b,c:b[2].update(loop_processed=0),False),
        ('delayed_queue',lambda r,b,c:b[2].update(loop_processed=2),False),
        ('unexpected_GBA',lambda r,b,c:b[1].update(gba_completed=2),False),
        ('loop_disabled',lambda r,b,c:c.update(synchronous_loop=False),False),
        ('unknown_policy',lambda r,b,c:c.update(thread_policy='anything'),False),
        ('serial_rejects_workers',lambda r,b,c:c.update(thread_policy='serial_contained'),False)]
    results={}
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)
        for name,mutate,passed in cases:
            r,b,c=copy.deepcopy((run,backend,config))
            if mutate:mutate(r,b,c)
            with (p/'replay-backend.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(backend[0]));w.writeheader();w.writerows(b)
            errors=check(p,rows,r,c)
            assert (not errors)==passed,(name,errors)
            results[name]=errors
    print(json.dumps({'status':'passed','cases':results},indent=2))
if __name__=='__main__':main()
