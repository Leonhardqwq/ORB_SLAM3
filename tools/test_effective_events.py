"""Known outcomes and deliberately corrupt traces; no SLAM observations fabricated."""
import argparse
import copy
import csv
import json
from pathlib import Path
import tempfile

from check_effective_events import audit


def fixture():
    times = [(0, 0, 2, 2, 13), (10, 14, 16, 17, 22),
             (20, 22, 30, 30, 34), (30, 35, 41, 42, 44), (40, 45, 46, 46, 49)]
    rows, online = [], []
    for i, (q, a, e, b, f) in enumerate(times):
        rows.append(dict(round=i, k=i-1, frame=i, release_ns=q, aT_ns=a, eT_ns=e,
                         aB_ns=b, eB_ns=f, state=2, resets=0, keyframes=int(i == 0),
                         ids='0;' if i == 0 else ''))
        online.append(dict(k=i-1, timestamp_s=float(i), state=2, x=1., y=2., z=3.))
    summary = dict(fixed=True, status='passed', evaluated=4, initialization_frame=0,
                   period_ns=10, threads_at_evaluation_start=1, threads_at_evaluation_end=1,
                   clock_pair_max_ns=1, keyframes_processed=1, empty_rounds=4,
                   invalid_pose_frames=0)
    run = dict(accepted=True, mode='fixed', kind='instrument', returncode=0, timed_out=False,
               sampled_peak_threads=1, replay=summary)
    return rows, online, run


def write(directory, rows, online, run):
    directory.mkdir()
    (directory/'run.json').write_text(json.dumps(run))
    for name, data in [('replay-events.csv', rows), ('replay-online.csv', online)]:
        with (directory/name).open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', type=Path, required=True)
    args = p.parse_args()
    cfg = dict(evaluation_frames=4, H=2, h_ns=10, tau_ns=10, cumulative_timing_limit_ns=100000)
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix='effective-check-') as tmp:
        def check(name, mutate=None, accepted=False):
            rows, online, run = copy.deepcopy(fixture())
            if mutate:
                mutate(rows, online, run)
            directory = Path(tmp)/name
            write(directory, rows, online, run)
            result, detail = audit(directory, cfg, args.reference)
            if (result['status'] == 'accounting_passed') != accepted:
                raise AssertionError((name, result))
            outcomes[name] = dict(status=result['status'], errors=result['errors'])
            return result, detail
        r, d = check('backlog_gaps_equality_and_one_ns_late', accepted=True)
        assert [x['D_ns'] for x in d] == [6, 10, 11, 6]
        assert [x['W_T_ns'] for x in d] == [1, 0, 1, 1]
        assert [x['W_B_ns'] for x in d] == [1, 0, 1, 0]
        assert [w['initial_state_ns'] for w in r['windows']] == [[0, 3], [0, 4]]
        assert r['backlog_frames'] == 4 and r['deadline_equal_frames'] == 1
        assert r['late_frames'] == 1 and r['empirical_success_windows'] == 1
        assert r['max_identity_error_ns'] == 0 and r['max_legacy_error_ns'] > 0
        def exact(rows, online, run):
            rows[0]['eB_ns'] = 3
            for row in rows[1:]:
                q = row['release_ns']
                row.update(aT_ns=q, eT_ns=q+2, aB_ns=q+2, eB_ns=q+3)
        r, d = check('zero_gap', exact, True)
        assert r['max_legacy_error_ns'] == r['max_identity_error_ns'] == 0
        def invalid(rows, online, run):
            rows[2]['state'] = online[2]['state'] = 3
            run['replay']['invalid_pose_frames'] = 1
        r, d = check('invalid_pose_not_latency_failure', invalid, True)
        assert r['windows'][0]['latency_success'] and not r['windows'][0]['timely_valid_success']
        check('negative_ready_gap', lambda r,o,m: r[2].update(aT_ns=21))
        check('time_reversed', lambda r,o,m: r[1].update(eT_ns=13))
        check('duplicate_k', lambda r,o,m: r[2].update(k=0))
        check('missing_row', lambda r,o,m: r.pop(2))
        check('missing_initial_history', lambda r,o,m: (r.pop(0), o.pop(0)))
        check('duplicate_keyframe', lambda r,o,m: r[1].update(ids='0;',keyframes=1))
        check('empty_round_summary_wrong', lambda r,o,m: m['replay'].update(empty_rounds=0))
        check('online_state_wrong', lambda r,o,m: o[2].update(state=3))
        check('wrong_summary_count', lambda r,o,m: m['replay'].update(evaluated=3))
        check('native_not_fixed', lambda r,o,m: m.update(mode='native_control'))
        check('cancelled_or_timeout', lambda r,o,m: m.update(accepted=False,timed_out=True))
        check('unexpected_worker', lambda r,o,m: m.update(sampled_peak_threads=2))
        check('changed_release_period', lambda r,o,m: r[3].update(release_ns=29))
        check('duplicate_frame', lambda r,o,m: r[2].update(frame=1))
    print(json.dumps({'status': 'passed', 'fixtures': outcomes}, indent=2))


if __name__ == '__main__':
    main()
