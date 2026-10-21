"""Audit all cells from the paired, serial feature extraction; never infer cap from timing."""
import csv
def check(path,cap,serial=True):
    errors=[]
    with (path/'replay-tracking.csv').open() as stream:
        rows=list(csv.DictReader(stream))
    for r in rows:
        if 'extraction_cell_cap' not in r:
            if cap:errors.append('missing_extraction_counts')
            continue  # historical runs without this optional policy
        if int(r['extraction_cell_cap'])!=cap:errors.append('extraction_policy_mismatch')
        c,n,k,b,m=(int(r['extraction_'+x]) for x in ['cells','candidates','retained','capped_cells','retained_cell_max'])
        if not (0<=k<=n and 0<=b<=c and 0<=m<=k):errors.append('extraction_count_range')
        if int(r['work_control']) and serial and c==0:errors.append('missing_extraction_cells')
        if cap:
            if not serial or m>cap or k>cap*c:errors.append('extraction_cap_exceeded')
            if (b==0)!=(k==n):errors.append('extraction_drop_accounting')
        elif k!=n or b:errors.append('extraction_disabled_changed_candidates')
    return errors
