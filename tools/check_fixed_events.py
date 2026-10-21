"""Validate trace structure; reconstruct with the paper's existing exact step."""
import argparse
import csv
from fractions import Fraction as F
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

def check(directory, contract, reference=None):
    run=json.loads((directory/'run.json').read_text())
    assert run['accepted'] and run['mode']=='fixed' and run['kind']=='instrument'
    raw=list(csv.DictReader((directory/'replay-events.csv').open()))
    rows=[{k:int(v) for k,v in row.items() if k!='ids'}|{'ids':row['ids']} for row in raw]
    selected=[row for row in rows if row['k']>=0]
    errors=[];seen=set();prior=None;total_kf=0
    for i,row in enumerate(rows):
        if row['round']!=i:errors.append(f'round:{i}')
        if not row['release_ns']<=row['aT_ns']<=row['eT_ns']<=row['aB_ns']<=row['eB_ns']:
            errors.append(f'time_order:{i}')
        if prior and row['aT_ns']<prior['eB_ns']:errors.append(f'overlap:{i}')
        ids=list(filter(None,row['ids'].split(';')))
        if len(ids)!=row['keyframes']:errors.append(f'count:{i}')
        for identity in ids:
            key=row['resets'],int(identity)
            if key in seen:errors.append(f'duplicate_keyframe:{i}')
            seen.add(key);total_kf+=1
        prior=row
    if [row['k'] for row in selected]!=list(range(contract['evaluation_frames'])):errors.append('evaluation_coverage')
    if len(selected)>1 and any(y['release_ns']-x['release_ns']!=contract['h_ns'] for x,y in zip(selected,selected[1:])):
        errors.append('release_period')
    if not total_kf:errors.append('no_mapping_feedback_observed')
    if run['replay'].get('threads_at_evaluation_start',1)!=1 or run['replay'].get('threads_at_evaluation_end',1)!=1:
        errors.append('unexpected_threads_at_stage_boundaries')
    if run['replay']['clock_pair_max_ns']>contract['cumulative_timing_limit_ns']:errors.append('clock_diagnostic_limit')
    result={'directory':str(directory),'structural_errors':errors,'rows':len(rows),
            'evaluated':len(selected),'keyframes_processed':total_kf,'sampled_peak_threads':run['sampled_peak_threads'],
            'structure_passed':not errors}
    if reference is None or errors:return result
    spec=importlib.util.spec_from_file_location('paper_evaluate',reference)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    # The reference loader requires explicit self edges. These are redundant:
    # e_T(k-1)<=e_B(k-1)<=a_T(k)<=e_T(k), established above.
    model=module.Model(('T','B'),((1,0,1),(0,1,0),(0,0,1),(1,1,1)),(0,1),
        F(contract['h_ns']),F(contract['tau_ns']),contract['H'],1,0,(F(0),F(0)),(),(),())
    record=[];window=[];bad_windows=[];state=None;previous=rows[rows.index(selected[0])-1]
    for row in selected:
        k=row['k'];release=row['release_ns']
        if k%contract['H']==0:
            state=tuple(F(max(0,previous[name]-release)) for name in ['eT_ns','eB_ns'])
            window=[]
        service=(F(row['eT_ns']-row['aT_ns']),F(row['eB_ns']-row['aB_ns']))
        state,complete=model.step(state,service)
        error_T=int(F(row['eT_ns']-release)-complete[0]);error_B=int(F(row['eB_ns']-release)-complete[1])
        rT=row['aT_ns']-max(release,previous['eB_ns']);rB=row['aB_ns']-row['eT_ns']
        value={'k':k,'error_T_ns':error_T,'error_B_ns':error_B,'gap_T_ns':rT,'gap_B_ns':rB}
        record.append(value);window.append(max(abs(error_T),abs(error_B)))
        if (k+1)%contract['H']==0 and max(window)>contract['cumulative_timing_limit_ns']:
            bad_windows.append(k//contract['H'])
        previous=row
    result.update(reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
        reference=str(reference),timing_limit_ns=contract['cumulative_timing_limit_ns'],
        timing_passed=not bad_windows,failed_windows=bad_windows,window_count=len(selected)//contract['H'],
        max_abs_error_ns=max(max(abs(x['error_T_ns']),abs(x['error_B_ns'])) for x in record),
        max_gap_T_ns=max(x['gap_T_ns'] for x in record),max_gap_B_ns=max(x['gap_B_ns'] for x in record),
        largest_errors=sorted(record,key=lambda x:max(abs(x['error_T_ns']),abs(x['error_B_ns'])),reverse=True)[:10])
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--contract',type=Path,required=True)
    p.add_argument('--reference',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();assert not a.output.exists()
    result=check(a.run,json.loads(a.contract.read_text()),a.reference)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['structure_passed'] and result.get('timing_passed',True) else 1)
