"""Known-time checker fixtures. These are not measurements of ORB-SLAM3."""
import argparse
import csv
import json
from pathlib import Path
import tempfile
from check_fixed_events import check

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    args=parser.parse_args()
    contract=json.loads((Path(__file__).resolve().parents[1]/'docs/fixed-measurement.json').read_text())
    results={}
    with tempfile.TemporaryDirectory(prefix='orb-checker-') as temp:
        for name,gap in [('exact_recurrence',0),('extra_dispatch_wait',200000)]:
            target=Path(temp)/name;target.mkdir()
            (target/'run.json').write_text(json.dumps({'accepted':True,'mode':'fixed','kind':'instrument',
                'sampled_peak_threads':1,'replay':{'clock_pair_max_ns':1}}))
            rows=[dict(round=0,k=-1,frame=0,release_ns=0,aT_ns=0,eT_ns=10000000,aB_ns=10000000,
                       eB_ns=30000000,state=2,resets=0,keyframes=1,ids='0;')]
            for k in range(contract['evaluation_frames']):
                release=100000000+k*contract['h_ns'];start=release+gap
                rows.append(dict(round=k+1,k=k,frame=k+1,release_ns=release,aT_ns=start,
                    eT_ns=start+10000000,aB_ns=start+10000000,eB_ns=start+30000000,
                    state=2,resets=0,keyframes=0,ids=''))
            with (target/'replay-events.csv').open('w',newline='') as out:
                writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            result=check(target,contract,args.reference)
            assert result['structure_passed']
            assert result['timing_passed']==(gap==0)
            assert result['max_abs_error_ns']==gap
            results[name]={'timing_passed':result['timing_passed'],'max_abs_error_ns':result['max_abs_error_ns']}
    print(json.dumps({'status':'passed','fixtures':results},indent=2))

if __name__=='__main__': main()
