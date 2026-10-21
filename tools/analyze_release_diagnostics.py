"""Locate observed release gaps without subtracting probes or changing model gates."""
import argparse, csv, hashlib, json, statistics, sys
from pathlib import Path
import numpy as np

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):return list(csv.DictReader(p.open()))
def metrics(values):
    a=np.asarray(values,dtype=float)
    return {'p50':float(np.quantile(a,.5)),'p95':float(np.quantile(a,.95)),
            'p99':float(np.quantile(a,.99)),'max':float(max(a))}

def release_parts(eligible,enter,wake,exit,start):
    assert enter<=wake<=exit<=start and eligible<=start
    boundaries=[eligible,max(eligible,enter),max(eligible,wake),max(eligible,exit),start]
    values=[b-a for a,b in zip(boundaries,boundaries[1:])]
    assert min(values)>=0 and sum(values)==start-eligible
    return dict(zip(['before_wait_ns','sleep_return_late_ns','spin_after_release_ns','after_spin_ns'],values))

def trace_summary(directory):
    events=rows(directory/'replay-events.csv'); traces=rows(directory/'replay-release.csv')
    context_enabled=json.loads((directory/'replay-summary.json').read_text())['release_diagnostics']==2
    selected=[x for x in events if int(x['k'])>=0];assert len(selected)==len(traces)
    prior=events[events.index(selected[0])-1];records=[]
    for r,t in zip(selected,traces):
        r={k:int(v) for k,v in r.items() if k!='ids'};t={k:int(v) for k,v in t.items()}
        assert r['k']==t['k'] and t['sleep_return_ns']<=t['spin_begin_ns']<=t['spin_exit_ns']<=t['probe_end_ns']<=r['aT_ns']
        eligible=max(r['release_ns'],int(prior['eB_ns']))
        parts=release_parts(eligible,t['wait_enter_ns'],t['sleep_return_ns'],t['spin_exit_ns'],r['aT_ns'])
        item={'k':r['k'],'gap_T_ns':r['aT_ns']-eligible,'gap_B_ns':r['aB_ns']-r['eT_ns'],**parts,
            'sleep_return_relative_release_ns':t['sleep_return_ns']-r['release_ns'],
            'spin_begin_relative_release_ns':t['spin_begin_ns']-r['release_ns'],
            'spin_exit_relative_release_ns':t['spin_exit_ns']-r['release_ns'],
            'max_poll_gap_ns':t['max_poll_gap_ns'],
            'max_poll_end_relative_release_ns':t['max_poll_end_ns']-r['release_ns'] if t['polls'] else None,
            'post_spin_probes_ns':t['probe_end_ns']-t['spin_exit_ns'],
            'post_probe_dispatch_ns':r['aT_ns']-t['probe_end_ns'],
            'involuntary_switches':t['involuntary_after']-t['involuntary_before'] if context_enabled else None,
            'voluntary_switches':t['voluntary_after']-t['voluntary_before'] if context_enabled else None,
            'spin_wall_ns':t['spin_exit_ns']-t['spin_begin_ns'],
            'thread_cpu_bracket_ns':t['thread_cpu_end_ns']-t['thread_cpu_begin_ns'] if context_enabled else None}
        item['largest_component']=max(parts,key=parts.get);records.append(item);prior=r
    keys=['gap_T_ns','gap_B_ns','before_wait_ns','sleep_return_late_ns','spin_after_release_ns','after_spin_ns',
          'post_spin_probes_ns','post_probe_dispatch_ns','max_poll_gap_ns']
    return {'checked_rows':len(records),'decomposition_exact':True,'context_probes_enabled':context_enabled,
        'metrics_ns':{key:metrics([r[key] for r in records]) for key in keys},
        'gap_above_100us':sum(r['gap_T_ns']>100000 for r in records),
        'late_wake_rows':sum(r['sleep_return_late_ns']>0 for r in records),
        'spin_involuntary_rows':sum((r['involuntary_switches'] or 0)>0 for r in records) if context_enabled else None,
        'largest_gaps':sorted(records,key=lambda r:r['gap_T_ns'],reverse=True)[:10],
        'involuntary_examples':sorted([r for r in records if (r['involuntary_switches'] or 0)>0],key=lambda r:r['gap_T_ns'],reverse=True)[:10]}

def companion(path,start=None,end=None):
    raw=rows(path)
    if start is not None:raw=[r for r in raw if start<=int(r['release_ns']) and int(r['end_ns'])<=end]
    assert len(raw)>=100
    return {'samples':len(raw),**{name:metrics([(int(r[b])-int(r[a]))/1e6 for r in raw]) for name,a,b in
        [('latency_ms','release_ns','end_ns'),('wakeup_ms','release_ns','start_ns'),('compute_ms','start_ns','end_ns')]}}

def analyze(batch,data,reference,support):
    sys.path.insert(0,str(support));from check_fixed_events import check;from score_online_trajectory import score
    identity=json.loads((batch/'inputs.json').read_text());cfg=identity['protocol'];results=[]
    for item in json.loads((batch/'runs.json').read_text()):
        directory=batch/item['name']/'replay';run=item['run'];summary=run['replay']
        assert run['accepted'] and summary['evaluated']==cfg['evaluation_frames']
        ev=[r for r in rows(directory/'replay-events.csv') if int(r['k'])>=0]
        lat=[(int(r['eT_ns'])-int(r['release_ns']))/1e6 for r in ev]
        record={k:item[k] for k in ['name','load','strategy','repeat','diagnostics']}
        record.update(release=trace_summary(directory),quality=score(directory/'replay-online.csv',data),
            resources={'CPU_cores':summary['evaluation_cpu_ns']/summary['evaluation_elapsed_ns'],
                'RSS_MiB':run['sampled_peak_RSS_bytes']/2**20,'throughput_hz':summary['evaluated']*1e9/summary['evaluation_elapsed_ns'],
                'latency_ms':metrics(lat),'deadline_fraction':sum(v<=cfg['tau_ns']/1e6 for v in lat)/len(lat)},
            reset_count=max(int(r['resets']) for r in ev),
            artifact_hashes={f.name:sha(f) for f in directory.iterdir() if f.is_file()})
        if item['strategy']!='native_control': record['model']=check(directory,cfg,reference)
        if item['load']=='opencv_companion':
            record['companion']={'before':companion(batch/(item['name']+'-before/load.csv')),
                'after':companion(batch/(item['name']+'-after/load.csv')),
                'together':companion(batch/(item['name']+'-load.csv'),int(ev[0]['release_ns']),int(ev[-1]['eB_ns']))}
        results.append(record)
    for r in results:
        native=[v for v in results if v['strategy']=='native_control' and v['load']==r['load']]
        q=r['quality'];res=r['resources'];qc=cfg['quality'];rc=cfg['resources']
        gates={'absolute_ATE':q['ATE_RMSE_m']<=qc['online_SE3_ATE_RMSE_max_m'],
            'valid_poses':q['valid_fraction']>=qc['valid_fraction_min'],
            'ground_truth_coverage':q['ground_truth_coverage']>=qc['ground_truth_coverage_min'],
            'deadline_fraction':res['deadline_fraction']>=rc['deadline_success_fraction_min'],
            'throughput':res['throughput_hz']>=rc['throughput_min_hz'],
            'absolute_CPU':res['CPU_cores']<=rc['mean_CPU_cores_max'],
            'RSS':res['RSS_MiB']*2**20<=rc['sampled_peak_RSS_max_bytes']}
        if r['strategy']!='native_control':
            gates['no_reset']=r['reset_count']<=qc['reset_count_max']
            if native:
                gates['relative_ATE']=q['ATE_RMSE_m']<=statistics.median(v['quality']['ATE_RMSE_m'] for v in native)*qc['fixed_vs_native_factor']+qc['fixed_vs_native_allowance_m']
                gates['relative_CPU']=res['CPU_cores']<=statistics.median(v['resources']['CPU_cores'] for v in native)*rc['fixed_vs_native_CPU_factor']+rc['fixed_vs_native_CPU_allowance_cores']
        if 'companion' in r:
            comp=r['companion'];val=comp['together']['latency_ms']['p95']
            gates['companion_historical']=val<=cfg['historical_companion_p95_ms']*rc['companion_p95_factor']+rc['companion_p95_allowance_ms']
            for side in ['before','after']:
                gates['companion_'+side]=val<=comp[side]['latency_ms']['p95']*rc['companion_p95_factor']+rc['companion_p95_allowance_ms']
        r['gates']=gates
    return {'input_manifest_sha256':sha(batch/'inputs.json'),'reference_sha256':sha(reference),
            'phase':identity['phase'],'results':results,'probability_stage':'not_entered'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['batch','data','reference','support-tools','output']:p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();result=analyze(a.batch,a.data,a.reference,a.support_tools)
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    for r in result['results']: print(r['name'],r.get('model',{}).get('max_abs_error_ns'),[k for k,v in r['gates'].items() if not v])
