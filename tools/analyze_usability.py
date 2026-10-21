"""Score the predeclared comparison; retain failures and separate all gates."""
import argparse,csv,hashlib,json,statistics
from pathlib import Path
import numpy as np
from check_fixed_events import check
from score_online_trajectory import score

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):return list(csv.DictReader(p.open()))
def companion_p95(path,start=None,end=None):
    data=rows(path)
    if start is not None:data=[r for r in data if start<=int(r['release_ns']) and int(r['end_ns'])<=end]
    assert len(data)>=100,'insufficient overlapping companion samples'
    latency=[(int(r['end_ns'])-int(r['release_ns']))/1e6 for r in data]
    return {'samples':len(data),'p95_ms':float(np.quantile(latency,.95)),
            'deadline_fraction':sum(v<=50 for v in latency)/len(latency)}

def analyze(work,data,protocol,reference,batch_name='usability-runs'):
    runs=work/batch_name;cfg=json.loads(protocol.read_text())
    identity=json.loads((runs/'inputs.json').read_text())
    assert sha(protocol)==identity['protocol_sha256'],'protocol drift'
    full=json.loads((runs/'comparison.json').read_text());results=[]
    alone=companion_p95(runs/'companion-alone/load.csv')
    for item in full:
        directory=runs/item['name']/'replay';run=item['run'];summ=run['replay']
        raw=rows(directory/'replay-events.csv');ev=[r for r in raw if int(r['k'])>=0]
        latency=np.array([(int(r['eT_ns'])-int(r['release_ns']))/1e6 for r in ev])
        quality=score(directory/'replay-online.csv',data)
        record={k:item[k] for k in ['name','strategy','load','repeat']}
        record.update(quality=quality,resources={
            'mean_CPU_cores':summ['evaluation_cpu_ns']/summ['evaluation_elapsed_ns'],
            'sampled_peak_RSS_MiB':run['sampled_peak_RSS_bytes']/2**20,
            'sampled_peak_threads':run['sampled_peak_threads'],
            'throughput_hz':summ['evaluated']/(summ['evaluation_elapsed_ns']/1e9),
            'latency_p95_ms':float(np.quantile(latency,.95)),
            'latency_p99_ms':float(np.quantile(latency,.99)),
            'latency_max_ms':float(max(latency)),
            'deadline_fraction':float(np.mean(latency<=cfg['tau_ns']/1e6)),
            'end_to_end_seconds':run['seconds']},
            hashes={p.name:sha(p) for p in directory.glob('*') if p.is_file()},
            period_ns=summ['period_ns'],spin_ns=summ['spin_ns'],
            reset_count=max(int(r['resets']) for r in ev))
        if item['strategy']!='native_control':
            record['model']=check(directory,cfg,reference)
            prior=raw[raw.index(ev[0])-1]
            record['backlog_frames']=sum(int(before['eB_ns'])>int(after['release_ns']) for before,after in zip([prior]+ev[:-1],ev))
        if item['load']=='opencv_companion':
            record['companion']=companion_p95(runs/(item['name']+'-load.csv'),int(ev[0]['release_ns']),int(ev[-1]['eB_ns']))
        results.append(record)
    quality=cfg['quality'];resource=cfg['resources']
    for r in results:
        native=[x for x in results if x['strategy']=='native_control' and x['load']==r['load']]
        refate=statistics.median(x['quality']['ATE_RMSE_m'] for x in native)
        refcpu=statistics.median(x['resources']['mean_CPU_cores'] for x in native)
        q=r['quality'];c=r['resources'];fixed=r['strategy']!='native_control'
        gates={
            'absolute_ATE':q['ATE_RMSE_m']<=quality['online_SE3_ATE_RMSE_max_m'],
            'valid_poses':q['valid_fraction']>=quality['valid_fraction_min'],
            'ground_truth_coverage':q['ground_truth_coverage']>=quality['ground_truth_coverage_min'],
            'no_reset':r['reset_count']<=quality['reset_count_max'] if fixed else None,
            'deadline_fraction':c['deadline_fraction']>=resource['deadline_success_fraction_min'],
            'throughput':c['throughput_hz']>=resource['throughput_min_hz'],
            'absolute_CPU':c['mean_CPU_cores']<=resource['mean_CPU_cores_max'],
            'RSS':c['sampled_peak_RSS_MiB']*2**20<=resource['sampled_peak_RSS_max_bytes']}
        if fixed:
            gates['relative_ATE']=q['ATE_RMSE_m']<=refate*quality['fixed_vs_native_factor']+quality['fixed_vs_native_allowance_m']
            gates['relative_CPU']=c['mean_CPU_cores']<=refcpu*resource['fixed_vs_native_CPU_factor']+resource['fixed_vs_native_CPU_allowance_cores']
        if r['load']=='opencv_companion':
            gates['companion_p95']=r['companion']['p95_ms']<=alone['p95_ms']*resource['companion_p95_factor']+resource['companion_p95_allowance_ms']
        r['practical_gates']=gates;r['practical_passed']=all(v for v in gates.values() if v is not None)
        r['model_passed']=r.get('model',{}).get('structure_passed',False) and r.get('model',{}).get('timing_passed',False) if fixed else None
    return {'protocol_sha256':sha(protocol),'paper_reference_sha256':sha(reference),
        'input_manifest_sha256':sha(runs/'inputs.json'),'companion_alone':alone,'results':results,
        'expected_runs':cfg['repetitions']*len(cfg['strategies'])*len(cfg['loads']),
        'completed_runs':len(results),'probability_stage':'not_entered'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['work','data','protocol','reference','output']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--batch-name',default='usability-runs')
    a=p.parse_args();result=analyze(a.work,a.data,a.protocol,a.reference,a.batch_name)
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    for r in result['results']:
        print(r['name'],json.dumps({'ATE_m':r['quality']['ATE_RMSE_m'],'CPU':r['resources']['mean_CPU_cores'],
            'deadline_fraction':r['resources']['deadline_fraction'],
            'max_model_us':r['model']['max_abs_error_ns']/1000 if 'max_abs_error_ns' in r.get('model',{}) else None,
            'failed_gates':[k for k,v in r['practical_gates'].items() if v is False],'model':r['model_passed']}),flush=True)
