"""Online camera-position ATE with rigid alignment, without scale fitting.

EuRoC body ground truth is converted using the camera's T_BS extrinsic.
Uses numpy only. Ground-truth timestamps are interpolated within a 20 ms gap.
"""
import argparse,csv,json,re
from pathlib import Path
import numpy as np

def rotation(q):
    w,x,y,z=q/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])

def slerp(a,b,u):
    a=a/np.linalg.norm(a);b=b/np.linalg.norm(b)
    dot=float(a@b)
    if dot<0:b=-b;dot=-dot
    if dot>0.9995:
        q=(1-u)*a+u*b
        return q/np.linalg.norm(q)
    theta=np.arccos(np.clip(dot,-1,1))
    return (np.sin((1-u)*theta)*a+np.sin(u*theta)*b)/np.sin(theta)

def rigid_errors(predicted,truth):
    if len(predicted)<3:raise ValueError('insufficient positions')
    x=predicted-predicted.mean(0);y=truth-truth.mean(0)
    u,s,vt=np.linalg.svd(x.T@y)
    if s[1]<1e-10:raise ValueError('degenerate alignment')
    sign=np.eye(3);sign[-1,-1]=np.linalg.det(u@vt)
    r=u@sign@vt
    return np.linalg.norm(x@r-y,axis=1)

def score(online,data,start_k=0,end_k=None):
    with online.open() as stream:
        rows=[r for r in csv.DictReader(stream) if int(r['k'])>=start_k
              and (end_k is None or int(r['k'])<end_k)]
    if not rows:raise ValueError('empty predeclared scoring interval')
    if start_k<0 or (end_k is not None and [int(r['k']) for r in rows]!=list(range(start_k,end_k))):
        raise ValueError('incomplete predeclared scoring interval')
    gt=np.loadtxt(data/'mav0/state_groundtruth_estimate0/data.csv',delimiter=',',comments='#')
    values=re.search(r'data:\s*\[([^]]+)\]',(data/'mav0/cam0/sensor.yaml').read_text(),re.S)
    tbc=np.fromstring(values[1],sep=',').reshape(4,4)[:3,3]
    t0=gt[0,0];times=(gt[:,0]-t0)/1e9
    pred=[];truth=[];valid=0
    for row in rows:
        p=np.array([float(row[k]) for k in ['x','y','z']])
        if int(row['state'])!=2 or not np.isfinite(p).all():continue
        valid+=1
        t=float(row['timestamp_s'])-t0/1e9
        j=int(np.searchsorted(times,t,side='right'))
        if j<1 or j>=len(times) or times[j]-times[j-1]>0.02:continue
        u=(t-times[j-1])/(times[j]-times[j-1])
        body=(1-u)*gt[j-1,1:4]+u*gt[j,1:4]
        camera=body+rotation(slerp(gt[j-1,4:8],gt[j,4:8],u))@tbc
        pred.append(p);truth.append(camera)
    errors=rigid_errors(np.array(pred),np.array(truth))
    return {'frames':len(rows),'start_k':start_k,'end_k_exclusive':end_k,'valid_frames':valid,'matched_frames':len(pred),
        'valid_fraction':valid/len(rows),'ground_truth_coverage':len(pred)/len(rows),
        'ATE_RMSE_m':float(np.sqrt(np.mean(errors**2))),'ATE_p95_m':float(np.quantile(errors,.95)),
        'ATE_max_m':float(max(errors)),'alignment':'SE3, scale fixed to 1',
        'pose':'online left-camera position; body GT + rotated T_BS translation'}

def selftest():
    a=np.array([[0.,0,0],[1,0,0],[0,1,0],[0,0,1],[2,3,1]])
    r=rotation(np.array([.5,.5,.5,.5]));b=a@r+np.array([3,4,5])
    assert max(rigid_errors(a,b))<1e-12
    assert max(rigid_errors(a,2*b))>.1 # no hidden scale correction
    try:rigid_errors(np.zeros((4,3)),np.ones((4,3)))
    except ValueError:pass
    else:raise AssertionError('degenerate path accepted')
    assert np.allclose(rotation(slerp(np.array([1.,0,0,0]),np.array([0.,0,0,1]),.5))@np.array([1.,0,0]),[0,1,0])
    print('trajectory tests passed: rigid transform, scale refusal, degeneracy, rotation interpolation')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--selftest',action='store_true')
    p.add_argument('--online',type=Path);p.add_argument('--data',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--start-k',type=int,default=0);p.add_argument('--end-k',type=int)
    a=p.parse_args()
    if a.selftest:selftest()
    else:
        result=score(a.online,a.data,a.start_k,a.end_k)
        if a.output:
            with a.output.open('x') as f:json.dump(result,f,indent=2)
        print(json.dumps(result,indent=2))
