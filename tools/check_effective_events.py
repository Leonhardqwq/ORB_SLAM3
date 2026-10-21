"""Audit effective-duration accounting, NOT a probabilistic model or prediction.

Old actual-start checks remain unchanged. Use integer nanoseconds and the paper's
existing exact step. No tolerance is added to the deadline; no negative gap clamp.
"""
import argparse
import csv
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_reference(path):
    spec = importlib.util.spec_from_file_location('effective_paper_evaluate', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def audit(directory, contract, reference):
    directory = Path(directory)
    errors = []
    result = {'directory': str(directory), 'status': 'acquisition_invalid',
              'errors': errors, 'probability_assumptions_verified': False,
              'identity_is_independent_validation': False}
    try:
        paths = [directory / p for p in ('run.json', 'replay-events.csv', 'replay-online.csv')]
        result['input_sha256'] = {p.name: sha(p) for p in paths}
        run = json.loads(paths[0].read_text(encoding='utf-8'))
        summary = run['replay']
        if not (run.get('accepted') is True and run['mode'] == 'fixed'
                and run['kind'] == 'instrument' and summary['fixed'] is True
                and summary['status'] == 'passed' and run['returncode'] == 0
                and run.get('timed_out') is False):
            errors.append('not_a_completed_fixed_instrument_run')
        with paths[1].open(newline='') as f:
            rows = [{k: (v if k == 'ids' else int(v)) for k, v in r.items()}
                    for r in csv.DictReader(f)]
        with paths[2].open(newline='') as f:
            online = list(csv.DictReader(f))
        if len(rows) != len(online):
            errors.append('online_event_length_mismatch')
        selected = [r for r in rows if r['k'] >= 0]
        n, horizon = contract['evaluation_frames'], contract['H']
        if n <= 0 or horizon <= 0 or n % horizon:
            raise ValueError('contract requires complete predeclared windows')
        if [r['k'] for r in selected] != list(range(n)):
            errors.append('evaluation_coverage')
        init = len(rows) - len(selected)
        if init < 1 or any(r['k'] != -1 for r in rows[:init]) or rows[init:] != selected:
            errors.append('missing_or_invalid_initial_history')
        if summary['evaluated'] != n or summary['initialization_frame'] + 1 != init:
            errors.append('summary_evaluation_mismatch')
        if summary['period_ns'] != contract['h_ns']:
            errors.append('summary_period_mismatch')
        if summary.get('self_checks', 0) or summary.get('release_diagnostics', 0):
            errors.append('diagnostic_run_not_measurement_pilot')
        if contract.get('thread_policy', 'legacy_single') == 'legacy_single':
            if (summary['threads_at_evaluation_start'] != 1 or summary['threads_at_evaluation_end'] != 1
                    or run['sampled_peak_threads'] != 1):
                errors.append('unexpected_threads')
        else:
            from check_contained_backend import check
            errors.extend(check(directory, rows, run, contract))
            result['input_sha256']['replay-backend.csv'] = sha(directory/'replay-backend.csv')
        if not 0 <= summary['clock_pair_max_ns'] <= contract['cumulative_timing_limit_ns']:
            errors.append('clock_resolution_diagnostic_failed')
        seen = set()
        keyframes = 0
        invalid = 0
        previous_sensor_time = None
        for i, r in enumerate(rows):
            if r['round'] != i:
                errors.append(f'round_index:{i}')
            if not r['release_ns'] <= r['aT_ns'] <= r['eT_ns'] <= r['aB_ns'] <= r['eB_ns']:
                errors.append(f'time_order:{i}')
            if i:
                prior = rows[i - 1]
                if r['aT_ns'] < prior['eB_ns']:
                    errors.append(f'predecessor_overlap:{i}')
                if r['resets'] < prior['resets']:
                    errors.append(f'reset_counter_decreased:{i}')
                if r['resets'] == prior['resets'] and r['frame'] <= prior['frame']:
                    errors.append(f'frame_order:{i}')
            ids = [int(s) for s in r['ids'].split(';') if s]
            if len(ids) != r['keyframes']:
                errors.append(f'keyframe_count:{i}')
            for identity in ids:
                key = r['resets'], identity
                if key in seen:
                    errors.append(f'duplicate_keyframe:{i}')
                seen.add(key)
            keyframes += len(ids)
            if i < len(online):
                o = online[i]
                if int(o['k']) != r['k'] or int(o['state']) != r['state']:
                    errors.append(f'online_state_mismatch:{i}')
                sensor_time = float(o['timestamp_s'])
                if not math.isfinite(sensor_time) or (previous_sensor_time is not None
                                                       and sensor_time <= previous_sensor_time):
                    errors.append(f'sensor_time_order:{i}')
                previous_sensor_time = sensor_time
                valid = r['state'] == 2 and all(math.isfinite(float(o[s])) for s in ('x', 'y', 'z'))
                if r['k'] >= 0 and not valid:
                    invalid += 1
        if any(y['release_ns'] - x['release_ns'] != contract['h_ns']
               for x, y in zip(selected, selected[1:])):
            errors.append('release_period')
        if keyframes != summary['keyframes_processed'] or keyframes == 0:
            errors.append('mapping_feedback_or_summary_mismatch')
        if sum(r['keyframes'] == 0 for r in rows) != summary['empty_rounds']:
            errors.append('empty_round_summary_mismatch')
        if invalid != summary['invalid_pose_frames']:
            errors.append('invalid_pose_summary_mismatch')
        if errors:
            return result, []
        module = load_reference(reference)
        F = Fraction
        model = module.Model(('T', 'B'), ((1, 0, 1), (0, 1, 0), (0, 0, 1), (1, 1, 1)),
                             (0, 1), F(contract['h_ns']), F(contract['tau_ns']), horizon,
                             1, 0, (F(0), F(0)), (), (), ())
        prior = rows[init - 1]
        detail, windows = [], []
        for r, o in zip(selected, online[init:]):
            release, k = r['release_ns'], r['k']
            ready = max(release, prior['eB_ns'])
            wT, wB = r['aT_ns'] - ready, r['aB_ns'] - r['eT_ns']
            cT, cB = r['eT_ns'] - r['aT_ns'], r['eB_ns'] - r['aB_ns']
            if min(wT, wB, cT, cB) < 0:
                raise ValueError('negative gap or execution duration')
            if k % horizon == 0:
                state = tuple(F(max(0, prior[s] - release)) for s in ('eT_ns', 'eB_ns'))
                legacy = state
                window = {'index': k // horizon, 'initial_state_ns': [int(s) for s in state],
                          'latency_success': True, 'timely_valid_success': True,
                          'identity_max_abs_ns': 0, 'legacy_max_abs_ns': 0}
            state, completed = model.step(state, (F(wT + cT), F(wB + cB)))
            legacy, old = model.step(legacy, (F(cT), F(cB)))
            observed = (r['eT_ns'] - release, r['eB_ns'] - release)
            identity_error = max(abs(int(x - y)) for x, y in zip(observed, completed))
            old_error = max(abs(int(x - y)) for x, y in zip(observed, old))
            timely = observed[0] <= contract['tau_ns']
            valid = r['state'] == 2 and all(math.isfinite(float(o[s])) for s in ('x', 'y', 'z'))
            window['latency_success'] &= timely
            window['timely_valid_success'] &= timely and valid
            window['identity_max_abs_ns'] = max(window['identity_max_abs_ns'], identity_error)
            window['legacy_max_abs_ns'] = max(window['legacy_max_abs_ns'], old_error)
            detail.append({'k': k, 'release_ns': release, 'ready_T_ns': ready,
                           'backlog_ns': max(0, prior['eB_ns'] - release),
                           'W_T_ns': wT, 'C_T_ns': cT, 'S_effective_T_ns': wT + cT,
                           'W_B_ns': wB, 'C_B_ns': cB, 'S_effective_B_ns': wB + cB,
                           'D_ns': observed[0], 'deadline_slack_ns': contract['tau_ns'] - observed[0],
                           'timely': timely, 'valid': valid, 'identity_error_ns': identity_error,
                           'legacy_error_ns': old_error, 'keyframes': r['keyframes']})
            if (k + 1) % horizon == 0:
                windows.append(window)
            prior = r
        result.update(status='accounting_passed' if all(w['identity_max_abs_ns'] == 0 for w in windows)
                      else 'accounting_failed', frames=len(detail), windows=windows,
                      sampled_peak_threads=run['sampled_peak_threads'], keyframes_processed=keyframes,
                      empty_rounds=summary['empty_rounds'], invalid_pose_frames=invalid,
                      backlog_frames=sum(d['backlog_ns'] > 0 for d in detail),
                      max_identity_error_ns=max(d['identity_error_ns'] for d in detail),
                      max_legacy_error_ns=max(d['legacy_error_ns'] for d in detail),
                      legacy_failed_windows=sum(w['legacy_max_abs_ns'] > contract['cumulative_timing_limit_ns'] for w in windows),
                      max_W_T_ns=max(d['W_T_ns'] for d in detail), max_W_B_ns=max(d['W_B_ns'] for d in detail),
                      late_frames=sum(not d['timely'] for d in detail),
                      deadline_equal_frames=sum(d['deadline_slack_ns'] == 0 for d in detail),
                      min_abs_deadline_slack_ns=min(abs(d['deadline_slack_ns']) for d in detail),
                      empirical_success_windows=sum(w['latency_success'] for w in windows),
                      reference_sha256=sha(reference))
        return result, detail
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        errors.append(f'{type(exc).__name__}: {exc}')
        return result, []


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'contract', 'reference', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    result, detail = audit(a.run, json.loads(a.contract.read_text(encoding='utf-8')), a.reference)
    result['contract_sha256'] = sha(a.contract)
    result['checker_sha256'] = sha(Path(__file__))
    (a.output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    if detail:
        with (a.output / 'durations.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(detail[0]))
            writer.writeheader()
            writer.writerows(detail)
    print(json.dumps({k: v for k, v in result.items() if k != 'windows'}, indent=2))
    return 0 if result['status'] == 'accounting_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
