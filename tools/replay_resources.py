"""Optional Linux replay affinity and diagnostic resource sampling.

Guest affinity restricts eligible virtual CPUs; it does not reserve host cores.
Never subtract recorded scheduling delay from measured service times.
"""
import csv
import os
from pathlib import Path
import re
import shutil
import time


def parse_cpus(value, allowed):
    if value is None:
        return None
    if not re.fullmatch(r'\d+(?:,\d+)*', value):
        raise ValueError('CPU list must be comma-separated nonnegative integers')
    cpus = tuple(int(x) for x in value.split(','))
    if len(set(cpus)) != len(cpus) or not set(cpus) <= set(allowed):
        raise ValueError('Repeated or unavailable CPU in explicit affinity')
    return tuple(sorted(cpus))


def launch_command(command, cpus):
    if cpus is None:
        return command
    taskset = shutil.which('taskset')
    if taskset is None:
        raise ValueError('Explicit affinity requires the existing Linux taskset utility')
    return [taskset, '--cpu-list', ','.join(map(str, cpus))] + command


def system_snapshot():
    return dict(allowed_cpus=sorted(os.sched_getaffinity(0)),
                clock_ticks_per_second=os.sysconf('SC_CLK_TCK'),
                kernel=os.uname().release,
                limits='Virtual CPU eligibility only; no host reservation or isolation guarantee')


def sample(pid, status):
    stat = Path(f'/proc/{pid}/stat').read_text().rpartition(') ')[2].split()
    sched = Path(f'/proc/{pid}/schedstat').read_text().split()
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    system = Path('/proc/stat').read_text().splitlines()[0].split()[1:]
    # CPU totals exclude guest fields, which are already included in user/nice.
    return dict(monotonic_ns=time.monotonic_ns(),
                leader_cpu_ticks=int(stat[11])+int(stat[12]),
                last_guest_cpu=int(stat[36]),
                leader_runtime_ns=int(sched[0]), leader_runqueue_wait_ns=int(sched[1]),
                voluntary_switches=int(fields.get('voluntary_ctxt_switches', 0)),
                nonvoluntary_switches=int(fields.get('nonvoluntary_ctxt_switches', 0)),
                allowed_cpu_list=fields['Cpus_allowed_list'].strip(),
                guest_total_ticks=sum(map(int, system[:8])),
                guest_idle_ticks=int(system[3]), guest_iowait_ticks=int(system[4]))


class Recorder:
    def __init__(self, path, cpus, executable=None):
        self.path = Path(path)
        self.cpus = cpus
        self.executable = Path(executable).resolve() if executable else None
        self.rows = []
        self.errors = []

    def observe(self, pid, status):
        try:
            # Popen returns before taskset has applied the mask and exec'd.
            if self.executable is not None and Path(f'/proc/{pid}/exe').resolve() != self.executable:
                return
            if self.executable is not None:
                status = Path(f'/proc/{pid}/status').read_text()
            row = sample(pid, status)
            if self.cpus is not None and set(os.sched_getaffinity(pid)) != set(self.cpus):
                self.errors.append('Observed child affinity differs from requested CPUs')
            self.rows.append(row)
        except ProcessLookupError:
            pass  # Child exited between status and diagnostic read.
        except FileNotFoundError:
            pass
        except (ValueError, IndexError, KeyError, PermissionError, OSError) as error:
            self.errors.append(type(error).__name__ + ': ' + str(error))

    def finish(self):
        if self.rows:
            with self.path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
                writer.writeheader(); writer.writerows(self.rows)
        else:
            self.errors.append('No usable resource samples')
        return dict(samples=len(self.rows), errors=sorted(set(self.errors)),
                    requested_cpus=self.cpus, recorded_path=str(self.path),
                    sampled_leader_only=True,
                    interpretation='Diagnostic counters, not whole-process CPU time or host contention proof')
