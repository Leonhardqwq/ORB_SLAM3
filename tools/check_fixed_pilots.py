"""Check the preregistered pilot gate before reconstructing any measured path."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
from check_fixed_events import check

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',type=Path,required=True)
    p.add_argument('--contract',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();assert not a.output.exists()
    contract=json.loads(a.contract.read_text())
    records={};structures={};errors=[]
    for kind in ['instrument','plain']:
        for n in range(1,contract['independent_runs_each']+1):
            name=f'pilot-{kind}-{n:02d}';directory=a.runs/name
            r=json.loads((directory/'run.json').read_text());records[name]=r
            if not r['accepted'] or r['replay']['evaluated']!=contract['evaluation_frames']:errors.append(name+':incomplete')
            if r['mode']!='fixed' or r['kind']!=kind:errors.append(name+':wrong_run')
            if r['sampled_peak_threads']!=1:errors.append(name+':unexpected_thread')
            if kind=='instrument':
                structures[name]=check(directory,contract)
                errors.extend(name+':'+e for e in structures[name]['structural_errors'])
    digests={json.dumps({key:r[key] for key in ['source_hashes','config_sha256','environment_overrides']},sort_keys=True) for r in records.values()}
    if len(digests)!=1:errors.append('inconsistent_run_inputs')
    def elapsed(kind):return [r['replay']['evaluation_elapsed_ns'] for r in records.values() if r['kind']==kind]
    ins=elapsed('instrument');plain=elapsed('plain')
    overhead=statistics.median(ins)/statistics.median(plain)-1
    observed_upper=max(ins)/min(plain)-1
    if overhead>contract['instrumentation_overhead_limit']:errors.append('instrumentation_overhead')
    elif observed_upper>contract['instrumentation_overhead_limit']:errors.append('overhead_evidence_insufficient')
    result={'contract_sha256':hashlib.sha256(a.contract.read_bytes()).hexdigest(),
        'stage3_passed':not errors,'stage3_errors':errors,'structures':structures,
        'instrumentation':{'instrument_elapsed_ns':ins,'plain_elapsed_ns':plain,
            'median_relative_overhead':overhead,'observed_extreme_relative_overhead':observed_upper,
            'limit':contract['instrumentation_overhead_limit'],
            'scope':'Replay elapsed time including release waiting; not a pure CPU overhead estimate or a confidence bound.'},
        'runs':{name:{k:v for k,v in r.items() if k not in ['source_hashes','command']} for name,r in records.items()}}
    if not errors:
        result['timing']={name:check(a.runs/name,contract,a.reference) for name in structures}
        result['stage4_passed']=all(r['timing_passed'] for r in result['timing'].values())
    else:result['stage4_status']='not_run_due_to_stage3'
    result['stop_after']='stage3' if errors else 'stage4' if not result['stage4_passed'] else None
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['runs','structures','timing']},indent=2))
    if 'timing' in result:
        for name,r in result['timing'].items():print(name,r['timing_passed'],r['max_abs_error_ns'],len(r['failed_windows']))
    return int(result['stop_after'] is not None)

if __name__=='__main__':raise SystemExit(main())
