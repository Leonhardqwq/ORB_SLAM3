"""Describe E3 coverage and temporal variation without fitting/validating F or Q."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np

from check_effective_events import sha


def describe(values):
    v=np.asarray(values,dtype=float)
    if not len(v):
        return {'n':0}
    return dict(n=len(v),min_ms=float(v.min()/1e6),median_ms=float(np.median(v)/1e6),
                p95_ms=float(np.quantile(v,.95)/1e6),max_ms=float(v.max()/1e6),mean_ms=float(v.mean()/1e6))


def rank(values):
    unique,inverse,counts=np.unique(values,return_inverse=True,return_counts=True)
    return (np.cumsum(counts)-counts/2)[inverse]


def correlation(x,y):
    a,b=rank(x),rank(y)
    if len(a)<3 or np.std(a)==0 or np.std(b)==0:
        return None
    return float(np.corrcoef(a,b)[0,1])


def run_metrics(path,cfg):
    with (path/'replay-events.csv').open() as f:
        rows=[{k:(v if k=='ids' else int(v)) for k,v in r.items()} for r in csv.DictReader(f)]
    values={k:[] for k in ('WT','WB','CT','CB','ST','SB','backlog','latency','keyframes','k','frame')}
    for prev,r in zip(rows,rows[1:]):
        if r['k']<0:
            continue
        wt=r['aT_ns']-max(r['release_ns'],prev['eB_ns'])
        wb=r['aB_ns']-r['eT_ns']
        ct=r['eT_ns']-r['aT_ns']; cb=r['eB_ns']-r['aB_ns']
        vals=(wt,wb,ct,cb,wt+ct,wb+cb,max(0,prev['eB_ns']-r['release_ns']),
              r['eT_ns']-r['release_ns'],r['keyframes'],r['k'],r['frame'])
        for key,value in zip(values,vals):values[key].append(value)
    v={k:np.asarray(x) for k,x in values.items()}
    delayed=v['backlog']>0
    late=v['latency']>cfg['tau_ns']
    h=cfg['H']
    windows=[bool(np.any(late[i:i+h])) for i in range(0,len(late),h)]
    return dict(evaluation_frames=len(late),frames=[int(v['frame'][0]),int(v['frame'][-1])],
      backlog_frames=int(sum(delayed)),late_frames=int(sum(late)),failed_latency_windows=sum(windows),windows=len(windows),
      backlog_k=v['k'][delayed].tolist(),late_k=v['k'][late].tolist(),
      duration={k:describe(v[k]) for k in ('WT','WB','CT','CB','ST','SB','backlog','latency')},
      conditional_descriptions={str(bool(state)):{k:describe(v[k][delayed==state]) for k in ('WT','CT','ST','SB')} for state in (False,True)},
      quarter_medians_ms={k:[float(np.median(part)/1e6) for part in np.array_split(v[k],4)] for k in ('ST','SB')},
      rank_serial_correlation={k:{str(lag):correlation(v[k][:-lag],v[k][lag:]) for lag in (1,2,5,10,20)} for k in ('WT','CT','CB','ST','SB')},
      same_round_ST_SB_rank_correlation=correlation(v['ST'],v['SB']),
      keyframe_rounds=int(sum(v['keyframes']>0)),
      interpretation='Descriptive exploratory statistics only; no iid-frame inference, independence acceptance or reliability confidence statement')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--collection',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    inputs=json.loads((a.collection/'inputs.json').read_text())
    result=json.loads((a.collection/'result.json').read_text())
    cfg=inputs['protocol']; records=[]
    for block in result['blocks']:
        for run in block['runs']:
            row={'block':block['name'],'strategy':run['strategy'],'record':run}
            if run['strategy']=='fixed_sleep' and not run.get('acquisition_failed'):
                row['coverage']=run_metrics(a.collection/block['name']/run['strategy']/'replay',cfg)
            records.append(row)
    out={'sequence':cfg['sequence'],'offset':cfg['offset'],'status':result['status'],
         'reason':result['reason'],'result_sha256':sha(a.collection/'result.json'),
         'inputs_sha256':sha(a.collection/'inputs.json'),'protocol':cfg,'records':records,
         'E4_permitted':False,'full_E3_passed':False}
    with a.output.open('x') as f:json.dump(out,f,indent=2,allow_nan=False)
    print(json.dumps({k:v for k,v in out.items() if k not in ('records','protocol')},indent=2))
    for r in records:
        print(r['block'],r['strategy'],'failed gates:',[k for k,v in r['record'].get('gates',{}).items() if not v],
              'coverage:',{k:v for k,v in r.get('coverage',{}).items() if k in ('backlog_frames','late_frames','frames')})


if __name__=='__main__':
    main()
