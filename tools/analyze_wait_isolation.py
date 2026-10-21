"""Summarize minimal waiting experiments, with guest event overlap diagnostics.

Overlap is observational and does not establish cause. No SLAM model certificate.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re


def quantile(values, p):
    values = sorted(values)
    pos = (len(values) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def stats(values):
    return {'min': min(values), 'median': quantile(values, .5), 'p95': quantile(values, .95),
            'p99': quantile(values, .99), 'max': max(values)}


def parse_trace(path):
    events = []
    # ftrace mono timestamps are printed to microsecond precision by this kernel.
    for line in path.read_text().splitlines():
        m = re.search(r'\s(\d+)\.(\d+):\s+(\w+):\s+(.*)', line)
        if m:
            timestamp = int(m[1]) * 1000000000 + int(m[2].ljust(9, '0')[:9])
            events.append({'ns': timestamp, 'name': m[3], 'details': m[4], 'line': line.strip()})
    return events


def trace_spans(events, pid):
    spans, switched_out, interrupts = [], None, {}
    for e in events:
        if e['name'] == 'sched_switch':
            if re.search(r'next_pid=' + str(pid) + r'\b', e['details']) and switched_out:
                spans.append({'kind': 'off_cpu', 'start_ns': switched_out['ns'], 'end_ns': e['ns'],
                              'entry': switched_out['line'], 'exit': e['line']})
                switched_out = None
            if re.search(r'prev_pid=' + str(pid) + r'\b', e['details']):
                switched_out = e
        if e['name'].endswith(('_entry', '_exit')):
            core = re.search(r'\[(\d+)\]', e['line'])
            key = (e['name'].rsplit('_', 1)[0], core[1] if core else '', e['details'].split()[0] if e['details'].strip() else '')
            if e['name'].endswith('_entry'):
                interrupts[key] = e
            elif key in interrupts:
                start = interrupts.pop(key)
                spans.append({'kind': key[0], 'start_ns': start['ns'], 'end_ns': e['ns'],
                              'entry': start['line'], 'exit': e['line']})
    return spans


def analyze(directory, cfg):
    rows = [{k: int(v) for k, v in r.items()} for r in csv.DictReader((directory/'probe-events.csv').open())]
    summary = json.loads((directory/'probe-summary.json').read_text())
    run = json.loads((directory/'run.json').read_text())
    assert len(rows) == cfg['rounds'] == summary['rounds']
    gaps, late, busy = [], [], []
    prior = rows[0]['release_ns']
    events = parse_trace(directory/'trace.txt') if (directory/'trace.txt').exists() else []
    spans = trace_spans(events, run.get('trace_pid', summary['pid']))
    if run.get('trace'):
        assert any(e['name']=='sched_switch' for e in events), 'trace missing positive control'
        assert any(e['name']=='sched_wakeup' for e in events), 'trace missing positive control'
    anomalies = []
    for i, r in enumerate(rows):
        assert r['k'] == i and r['start_ns'] >= r['release_ns'] and r['end_ns'] >= r['start_ns']
        if i:
            assert r['release_ns'] - rows[i-1]['release_ns'] == cfg['period_ns']
            assert r['start_ns'] >= prior
        gap = r['start_ns'] - max(r['release_ns'], prior)
        gaps.append(gap/1000)
        late.append((r['start_ns']-r['release_ns'])/1000)
        busy.append((r['end_ns']-r['start_ns'])/1000)
        if gap > cfg['diagnostic_threshold_ns'] or r['max_poll_gap_ns'] > cfg['diagnostic_threshold_ns']:
            lo = r['max_poll_end_ns']-r['max_poll_gap_ns'] if r['max_poll_gap_ns'] > cfg['diagnostic_threshold_ns'] else max(r['release_ns'], prior)
            hi = r['max_poll_end_ns'] if r['max_poll_gap_ns'] > cfg['diagnostic_threshold_ns'] else r['start_ns']
            # Include whole spin/wake-to-start context for interpretation; mark narrower overlap.
            relevant = [dict(e, overlaps_interval=(lo-1000 <= e['ns'] <= hi+1000)) for e in events
                        if min(lo, r['sleep_return_ns'] or lo)-10000 <= e['ns'] <= r['start_ns']+10000]
            overlap = [s for s in spans if s['start_ns'] <= hi+1000 and s['end_ns'] >= lo-1000]
            anomalies.append({'k': i, 'gap_us': gap/1000, 'interval_ns': [lo, hi],
                              'row': r, 'guest_events': relevant, 'overlapping_guest_spans': overlap})
        prior = r['end_ns']
    loss = {}
    for core, s in run.get('trace_stats', {}).items():
        counts = {m[1]: int(m[2]) for m in re.finditer(r'^(overrun|commit overrun|dropped events):\s*(\d+)',s,re.M)}
        loss[core] = counts
    clocks = []
    if summary['probes']:
        for r in rows:
            wall = r['spin_exit_ns']-r['sleep_return_ns']
            raw = r['raw_exit_ns']-r['raw_wake_ns']
            clocks.append((raw-wall)/1000)
    return {'name': directory.name, 'summary': summary, 'gap_us': stats(gaps),
            'release_lateness_us': stats(late), 'work_wall_us': stats(busy),
            'gaps_above_100us': sum(g > 100 for g in gaps),
            'cpu_fraction': summary['cpu_ns']/summary['wall_ns'],
            'max_poll_gap_us': max(r['max_poll_gap_ns'] for r in rows)/1000,
            'spin_involuntary_switches': sum(r['invol_after']-r['invol_before'] for r in rows),
            'spin_cpu_migrations': sum(r['cpu_wake']!=r['cpu_exit'] for r in rows),
            'raw_minus_monotonic_interval_us': stats(clocks) if clocks else None,
            'trace_event_counts': {name: sum(e['name']==name for e in events) for name in sorted({e['name'] for e in events})},
            'trace_loss_counts': loss, 'anomalies': anomalies,
            'files_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in directory.iterdir() if f.is_file()}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--traced-dir',default='traced')
    p.add_argument('--extra-traced-dir',help='Optional separately declared diagnostic supplement')
    p.add_argument('--host-stream-dir',help='Optional file-mode host diagnostic supplement')
    a=p.parse_args()
    assert not a.out.exists(), 'refuse overwrite'
    result={}
    for phase in ['baseline','traced']:
        base=a.root/(a.traced_dir if phase=='traced' else phase)
        if not base.exists(): continue
        manifest=json.loads((base/'manifest.json').read_text())
        result[phase]={'manifest':manifest,'runs':[analyze(d,manifest['protocol']) for d in sorted(base.iterdir()) if d.is_dir() and (d/'run.json').exists()]}
    for extra_phase,extra_dir in [('irq_vectors',a.extra_traced_dir),('host_stream',a.host_stream_dir)]:
        if not extra_dir: continue
        base=a.root/extra_dir
        manifest=json.loads((base/'manifest.json').read_text())
        result[extra_phase]={'manifest':manifest,'runs':[analyze(d,manifest['protocol']) for d in sorted(base.iterdir()) if d.is_dir() and (d/'run.json').exists()]}
    a.out.write_text(json.dumps(result,indent=2)+'\n')
    for phase,data in result.items():
        for r in data['runs']:
            print(phase,r['name'],'max_us',r['gap_us']['max'],'above100',r['gaps_above_100us'],'poll_max_us',r['max_poll_gap_us'])


if __name__=='__main__': main()
