"""Independent, serial configuration diagnostics. Never an E3/E4 pass by itself."""
import argparse,csv,hashlib,json,subprocess,sys,time
from pathlib import Path
from score_online_trajectory import score
from check_effective_events import audit
from run_effective_collection import sequence_inputs

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['source','data','output','reference','protocol']:p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();cfg=json.loads(a.protocol.read_text());a.output.mkdir(parents=True,exist_ok=False)
    tools=Path(__file__).resolve().parent
    timestamps,settings,images=sequence_inputs(a.source,a.data,cfg)
    inputs={'images':images,'timestamps_sha256':sha(timestamps),'settings_sha256':sha(settings),
        'ground_truth_sha256':sha(a.data/'mav0/state_groundtruth_estimate0/data.csv'),
        'camera_sensor_sha256':sha(a.data/'mav0/cam0/sensor.yaml'),
        'tools':{n:sha(tools/n) for n in ['run_contained_backend_comparison.py','run_fixed_replay.py',
            'run_effective_collection.py','check_effective_events.py','check_contained_backend.py','score_online_trajectory.py']}}
    (a.output/'inputs.json').write_text(json.dumps(inputs,indent=2))
    manifest={'protocol':cfg,'protocol_sha256':sha(a.protocol),'runner_sha256':sha(Path(__file__)),
        'source':str(a.source),'binary_sha256':sha(a.source/'Examples/Stereo/stereo_fixed_replay'),
        'library_sha256':sha(a.source/'lib/libORB_SLAM3.so'),'reference_sha256':sha(a.reference),
        'python':sys.version,'inputs_sha256':sha(a.output/'inputs.json'),'results':[],
        'probability_assumptions_verified':False,'full_E3_passed':False}
    (a.output/'results.json').write_text(json.dumps(manifest,indent=2))
    for block,order in enumerate(cfg['orders'],1):
        records=[]
        for name in order:
            c=cfg['configurations'][name];out=a.output/f'block-{block}-{name}'
            cmd=[sys.executable,str(tools/'run_fixed_replay.py'),'--source',str(a.source),'--data',str(a.data),
                '--output',str(out),'--mode',c['mode'],'--serial-stereo',str(c['serial']),
                '--synchronous-loop',str(c['loop']),'--frames',str(cfg['evaluation_frames']),
                '--preload-limit',str(cfg['preload_limit']),'--period-ns',str(cfg['h_ns']),
                '--threads','1','--spin-us','0','--timeout',str(cfg['timeout_seconds']),
                '--offset',str(cfg['offset']),'--init-limit',str(cfg['initialization_limit']),
                '--settings',str(settings),'--timestamps',str(timestamps)]
            with (a.output/f'block-{block}-{name}-runner.log').open('w') as f:
                r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
            run=json.loads((out/'run.json').read_text())
            rec={'block':block,'configuration':name,'command':cmd,'path':str(out),'run_sha256':sha(out/'run.json'),
                 'completed':run['accepted'],'returncode':r.returncode}
            if run['accepted']:
                assert run['binary_sha256']==manifest['binary_sha256']
                assert run['loaded_library']['sha256']==manifest['library_sha256']
                s=run['replay'];rec['quality']=score(out/'replay-online.csv',a.data,cfg['quality_start_k'],cfg['evaluation_frames'])
                rec.update(invalid_frames=s['invalid_pose_frames'],cpu_cores=s['evaluation_cpu_ns']/s['evaluation_elapsed_ns'],
                    RSS_bytes=run['sampled_peak_RSS_bytes'],sampled_peak_threads=run['sampled_peak_threads'],
                    throughput_hz=s['evaluated']/(s['evaluation_elapsed_ns']/1e9))
                with (out/'replay-events.csv').open() as f:events=list(csv.DictReader(f))
                e=[x for x in events if int(x['k'])>=0]
                late=[int(x['eT_ns'])-int(x['release_ns'])>cfg['tau_ns'] for x in e]
                rec.update(late_frames=sum(late),deadline_fraction=1-sum(late)/len(e),
                    max_T_ms=max(int(x['eT_ns'])-int(x['aT_ns']) for x in e)/1e6,
                    max_B_ms=max(int(x['eB_ns'])-int(x['aB_ns']) for x in e)/1e6,
                    max_latency_ms=max(int(x['eT_ns'])-int(x['release_ns']) for x in e)/1e6,
                    resets=int(e[-1]['resets']) if c['mode']=='fixed' else None,
                    reset_counter_supported=c['mode']=='fixed')
                rec['loop_console']=[line for line in (out/'console.log').read_text(errors='replace').splitlines() if 'loop detected' in line.lower()]
                gates=dict(ATE=rec['quality']['ATE_RMSE_m']<=.15,
                    valid=1-rec['invalid_frames']/len(e)>=.99,GT=rec['quality']['ground_truth_coverage']>=.99,
                    deadline=rec['deadline_fraction']>=.99,throughput=rec['throughput_hz']>=19,
                    CPU=rec['cpu_cores']<=1,RSS=rec['RSS_bytes']<=2*1024**3)
                if c['mode']=='fixed':
                    contract=dict(cfg,thread_policy='joined_stereo' if c['serial']==0 else 'serial_contained',synchronous_loop=bool(c['loop']))
                    account,detail=audit(out,contract,a.reference)
                    (out/'accounting.json').write_text(json.dumps(account,indent=2))
                    with (out/'durations.csv').open('w',newline='') as f:
                        if detail:
                            w=csv.DictWriter(f,fieldnames=list(detail[0]));w.writeheader();w.writerows(detail)
                    rec['accounting']={k:v for k,v in account.items() if k not in ['windows']}
                    rec['successful_windows']=account.get('empirical_success_windows')
                    with (out/'replay-backend.csv').open() as f:b=list(csv.DictReader(f))
                    rec['backend_final']=b[-1];prev={n:0 for n in ['loop_corrected','maps_merged','gba_completed']}
                    rec['backend_events']=[]
                    for x,ev in zip(b,events):
                        if any(int(x[n])!=prev[n] for n in prev):
                            rec['backend_events'].append(dict(x,B_ms=(int(ev['eB_ns'])-int(ev['aB_ns']))/1e6))
                        prev={n:int(x[n]) for n in prev}
                    gates.update(no_resets=rec['resets']==0,accounting=account['status']=='accounting_passed')
                rec['gates']=gates;rec['absolute_passed']=all(gates.values())
            records.append(rec);manifest['results'].append(rec)
            (a.output/'results.json').write_text(json.dumps(manifest,indent=2))
            print(json.dumps({k:rec[k] for k in ['block','configuration','completed','quality','deadline_fraction','max_B_ms','gates'] if k in rec}),flush=True)
            if not run['accepted']:raise RuntimeError('Acquisition error: preserve evidence, diagnose before more runs')
        native=next(r for r in records if r['configuration']=='native-default')
        for rec in records:
            if rec['configuration']!='native-default':
                rec['relative_gates']=dict(ATE=rec['quality']['ATE_RMSE_m']<=1.25*native['quality']['ATE_RMSE_m']+.02,
                    CPU=rec['cpu_cores']<=1.2*native['cpu_cores']+.02)
        (a.output/'results.json').write_text(json.dumps(manifest,indent=2))
    print('Predeclared diagnostics completed. E3/E4 status requires separate review.',flush=True)
if __name__=='__main__':main()
