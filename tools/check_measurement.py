"""Check deadline semantics separately from visual validity and missing evidence."""
import json

def classify(release, end, tau, valid=True, missing=False, duplicates=False, uncertainty=0):
    if tau < 0 or uncertainty < 0: raise ValueError('negative parameter')
    if duplicates or (end is None and not missing): return ('record_error', None)
    if missing: return ('failure_no_output', False)
    if end < release: return ('record_error', None)
    delay = end - release
    timing = 'success' if delay + uncertainty <= tau else 'failure' if delay - uncertainty > tau else 'unresolved'
    joint = False if not valid or timing == 'failure' else True if timing == 'success' else None
    return timing, joint

def self_check():
    cases = [
        ('normal', (0, 40, 50), ('success', True)),
        ('equality', (0, 50, 50), ('success', True)),
        ('late', (0, 51, 50), ('failure', False)),
        ('no_output', (0, None, 50, True, True), ('failure_no_output', False)),
        ('invalid_pose', (0, 40, 50, False), ('success', False)),
        # B(-1)=30, S_T=25 gives T(0)=55. Waiting cannot be ignored.
        ('backlog', (0, 55, 50), ('failure', False)),
        ('lost_log', (0, None, 50), ('record_error', None)),
        ('duplicate', (0, 40, 50, True, False, True), ('record_error', None)),
        ('uncertain_equality', (0, 50, 50, True, False, False, 1), ('unresolved', None)),
    ]
    results = []
    for name, args, expected in cases:
        actual = classify(*args)
        assert actual == expected, (name, actual, expected)
        results.append({'case': name, 'expected': expected, 'actual': actual})
    return {'status': 'passed', 'cases': results}

if __name__ == '__main__': print(json.dumps(self_check(), indent=2))
