"""E3 paired feasibility blocks with interleaved companion-only controls.

Stops after the first completed block that fails a declared gate. A passing block
does not establish adequate data for fitting, conditional independence or safety.
"""
import argparse
import bisect
import csv
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

from analyze_usability import companion_p95
from check_effective_events import audit, sha
from run_usability_batch import command
from score_online_trajectory import score


def sequence_inputs(source, data, cfg):
    """Fail before replay if sequence-specific inputs are missing or mismatched."""
    if data.name != cfg['sequence']:
        raise ValueError('data directory does not match protocol sequence')
    timestamp_name = cfg.get('timestamps')
    if timestamp_name is None:
        if cfg['sequence'] != 'V1_01_easy':
            raise ValueError('non-V101 sequence requires explicit timestamps')
        timestamp_name = 'Examples/Stereo/EuRoC_TimeStamps/V101.txt'
    timestamps = (source/timestamp_name).resolve()
    settings = (source/cfg.get('settings','Examples/Stereo/EuRoC.yaml')).resolve()
    stamps = timestamps.read_text().splitlines()
    if cfg['offset'] < 0 or cfg['offset']+cfg['preload_limit'] > len(stamps):
        raise ValueError('predeclared segment exceeds sequence')
    if cfg['preload_limit'] < cfg['evaluation_frames']+cfg['initialization_limit']:
        raise ValueError('preload may not cover initialization plus evaluation')
    with (data/'mav0/state_groundtruth_estimate0/data.csv').open() as f:
        ground_truth=[int(line.split(',')[0]) for line in f if line.strip() and not line.startswith('#')]
    if ground_truth!=sorted(set(ground_truth)):
        raise ValueError('invalid ground-truth timestamp order')
    available=[]
    for stamp in stamps:
        j=bisect.bisect_right(ground_truth,int(stamp))
        available.append(0<j<len(ground_truth) and ground_truth[j]-ground_truth[j-1]<=20000000)
    # Protect every initialization outcome allowed by the protocol, before replay.
    scoring=cfg.get('quality_interval',{'start_k':0,'end_k':cfg['evaluation_frames']})
    if not 0<=scoring['start_k']<scoring['end_k']<=cfg['evaluation_frames']:
        raise ValueError('invalid scoring interval')
    length=scoring['end_k']-scoring['start_k']
    for initialization in range(1,cfg['initialization_limit']+1):
        begin=cfg['offset']+initialization+scoring['start_k']
        valid=available[begin:begin+length]
        if len(valid)!=length or sum(valid)/len(valid)<cfg['quality']['ground_truth_coverage_min']:
            raise ValueError('predeclared segment lacks ground truth for an allowed initialization')
    digest = {}
    for cam in ('cam0','cam1'):
        for stamp in stamps[cfg['offset']:cfg['offset']+cfg['preload_limit']]:
            image = data/'mav0'/cam/'data'/(stamp+'.png')
            digest[image.relative_to(data).as_posix()] = sha(image)
    return timestamps, settings, digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('source','data','output','protocol','reference','e2-result','companion'):
        p.add_argument('--'+n, type=Path, required=True)
    a=p.parse_args()
    if json.loads(a.e2_result.read_text())['status']!='passed':
        raise ValueError('E2 must pass first')
    cfg=json.loads(a.protocol.read_text(encoding='utf-8'))
    tools=Path(__file__).resolve().parent
    a.output.mkdir(parents=True,exist_ok=False)
    prior_inputs=json.loads((a.e2_result.parent/'inputs.json').read_text())
    for name,digest in prior_inputs['source'].items():
        if sha(a.source/name)!=digest:raise ValueError('source changed since E2: '+name)
    if sha(a.source/'Examples/Stereo/stereo_fixed_replay')!=prior_inputs['binary_sha256']:
        raise ValueError('binary changed since E2')
    if sha(Path(prior_inputs['library']))!=prior_inputs['library_sha256']:
        raise ValueError('shared library changed since E2')
    dependencies=subprocess.check_output(['ldd',str(a.source/'Examples/Stereo/stereo_fixed_replay')],text=True)
    linked=re.search(r'libORB_SLAM3\.so\s+=>\s+(.*?)\s+\(',dependencies)
    if not linked or 'not found' in dependencies or Path(linked[1]).resolve()!=Path(prior_inputs['library']).resolve():
        raise ValueError('runtime library resolution changed since E2')
    timestamps,settings,images=sequence_inputs(a.source,a.data,cfg)
    stamp=timestamps.read_text().splitlines()[cfg['offset']]
    image=a.data/'mav0/cam0/data'/(stamp+'.png')
    inputs={'protocol':cfg,'protocol_sha256':sha(a.protocol),'e2_result_sha256':sha(a.e2_result),
            'e2_inputs_sha256':sha(a.e2_result.parent/'inputs.json'),
            'companion_binary_sha256':sha(a.companion),'companion_image_sha256':sha(image),
            'timestamps_sha256':sha(timestamps),'settings_sha256':sha(settings),
            'reference_sha256':sha(a.reference),
            'sequence':cfg['sequence'],'data':{s:sha(a.data/s) for s in ('mav0/cam0/data.csv','mav0/cam1/data.csv','mav0/state_groundtruth_estimate0/data.csv')},
            'images':images,
            'tools':{n:sha(tools/n) for n in ('run_effective_collection.py','run_fixed_replay.py',
                      'check_effective_events.py','score_online_trajectory.py','analyze_usability.py','run_usability_batch.py')}}
    (a.output/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    (a.output/'dependencies.txt').write_text(dependencies)
    blocks=[]
    def finish(status,reason):
        result={'stage':'E3','status':status,'reason':reason,'blocks':blocks,
                'probability_stage':'not_entered','full_E3_passed':False}
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'stage':'E3','status':status,'reason':reason},indent=2),flush=True)
        return 0 if status=='first_block_set_passed' else 1
    for name in cfg['blocks']:
        load,rep=name.rsplit('-',1);rep=int(rep)
        block={'name':name,'load':load,'repeat':rep,'runs':[]}
        blocks.append(block)
        target=a.output/name;target.mkdir()
        def alone(label):
            directory=target/label
            result=command([a.companion,image,'load.csv',cfg['companion_alone_seconds']],directory,60)
            if result['returncode']:raise RuntimeError('companion-only failure')
            return {'command':result,'score':companion_p95(directory/'load.csv'),
                    'sha256':sha(directory/'load.csv')}
        try:
            if load=='opencv_companion':block['before']=alone('alone-before')
            for strategy in cfg['strategy_order'][rep-1]:
                directory=target/strategy
                companion=None
                if load=='opencv_companion':
                    companion=subprocess.Popen([str(a.companion),str(image),str(target/(strategy+'-load.csv')),
                                                str(cfg['timeout_seconds']+20)],start_new_session=True)
                    time.sleep(.2)
                try:
                    execution=command([sys.executable,tools/'run_fixed_replay.py','--source',a.source,
                        '--data',a.data,'--output',directory/'replay','--mode',
                        'fixed' if strategy=='fixed_sleep' else 'native_control','--kind','instrument',
                        '--settings',settings,'--timestamps',timestamps,
                        '--frames',cfg['evaluation_frames'],'--offset',cfg['offset'],'--init-limit',cfg['initialization_limit'],
                        '--preload-limit',cfg['preload_limit'],'--period-ns',cfg['h_ns'],
                        '--threads',cfg['process_threads'],'--spin-us',cfg['spin_us'],
                        '--timeout',cfg['timeout_seconds']],directory,cfg['timeout_seconds']+15)
                finally:
                    if companion:
                        companion.terminate()
                        try:companion.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            companion.kill();companion.wait()
                path=directory/'replay'
                runpath=path/'run.json'
                run=json.loads(runpath.read_text()) if runpath.exists() else {}
                record={'strategy':strategy,'execution':execution,'run_json_sha256':sha(runpath) if runpath.exists() else None}
                block['runs'].append(record)
                if execution['returncode'] or not run.get('accepted'):
                    record['acquisition_failed']=True
                    continue
                with (path/'replay-events.csv').open() as f:
                    ev=[r for r in csv.DictReader(f) if int(r['k'])>=0]
                interval=cfg.get('quality_interval',{'start_k':0,'end_k':cfg['evaluation_frames']})
                q=score(path/'replay-online.csv',a.data,interval['start_k'],interval['end_k'])
                summary=run['replay']
                record.update(quality=q,CPU=summary['evaluation_cpu_ns']/summary['evaluation_elapsed_ns'],
                              throughput=summary['evaluated']/(summary['evaluation_elapsed_ns']/1e9),
                              RSS=run['sampled_peak_RSS_bytes'],
                              deadline_fraction=sum(int(r['eT_ns'])-int(r['release_ns'])<=cfg['tau_ns'] for r in ev)/len(ev),
                              reset_count=max(int(r['resets']) for r in ev),
                              full_run_valid_fraction=(summary['evaluated']-summary['invalid_pose_frames'])/summary['evaluated'],
                              reset_counter_supported=strategy=='fixed_sleep',
                              data_sha256={s:sha(path/s) for s in ('replay-events.csv','replay-online.csv','replay-summary.json')})
                if strategy=='fixed_sleep':record['accounting']=audit(path,cfg,a.reference)[0]
                if load=='opencv_companion':
                    record['companion']=companion_p95(target/(strategy+'-load.csv'),int(ev[0]['release_ns']),int(ev[-1]['eB_ns']))
                (a.output/'blocks-checkpoint.json').write_text(json.dumps(blocks,indent=2)+'\n')
            if load=='opencv_companion':block['after']=alone('alone-after')
        except (OSError,RuntimeError,ValueError,KeyError) as exc:
            block['error']=str(exc)
            return finish('failed','acquisition_or_scoring_error')
        if any(r.get('acquisition_failed') for r in block['runs']):
            return finish('failed','acquisition_failed')
        native=next(r for r in block['runs'] if r['strategy']=='native_control')
        qcfg,rcfg=cfg['quality'],cfg['resources']
        if load=='opencv_companion':
            base=statistics.median(block[s]['score']['p95_ms'] for s in ('before','after'))
            block['companion_reference_p95_ms']=base
        for r in block['runs']:
            q=r['quality'];fixed=r['strategy']=='fixed_sleep'
            gates={'absolute_ATE':q['ATE_RMSE_m']<=qcfg['online_SE3_ATE_RMSE_max_m'],
                   'valid_poses':q['valid_fraction']>=qcfg['valid_fraction_min'],
                   'full_run_valid_poses':r['full_run_valid_fraction']>=qcfg['valid_fraction_min'],
                   'ground_truth_coverage':q['ground_truth_coverage']>=qcfg['ground_truth_coverage_min'],
                   'deadline_fraction':r['deadline_fraction']>=rcfg['deadline_success_fraction_min'],
                   'throughput':r['throughput']>=rcfg['throughput_min_hz'],
                   'CPU':r['CPU']<=rcfg['mean_CPU_cores_max'],'RSS':r['RSS']<=rcfg['sampled_peak_RSS_max_bytes']}
            if fixed:
                gates.update(no_reset=r['reset_count']<=qcfg['reset_count_max'],
                    relative_ATE=q['ATE_RMSE_m']<=native['quality']['ATE_RMSE_m']*qcfg['fixed_vs_native_factor']+qcfg['fixed_vs_native_allowance_m'],
                    relative_CPU=r['CPU']<=native['CPU']*rcfg['fixed_vs_native_CPU_factor']+rcfg['fixed_vs_native_CPU_allowance_cores'],
                    accounting=r['accounting']['status']=='accounting_passed')
            if load=='opencv_companion':
                gates['companion_p95']=r['companion']['p95_ms']<=base*rcfg['companion_p95_factor']+rcfg['companion_p95_allowance_ms']
            r['gates']=gates
            print(name,r['strategy'],'failed gates',[g for g,v in gates.items() if not v],flush=True)
        if any(not v for r in block['runs'] for v in r['gates'].values()):
            return finish('failed','predeclared_practical_or_accounting_gate')
        (a.output/'blocks-checkpoint.json').write_text(json.dumps(blocks,indent=2)+'\n')
    return finish('first_block_set_passed','requires_further_sequence_and_sample_sufficiency_before_E4')


if __name__=='__main__':
    raise SystemExit(main())
