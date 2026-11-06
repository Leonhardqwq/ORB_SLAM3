"""Four compact exploratory figures from analyze.py outputs (matplotlib)."""
import argparse
import csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def load(path):
    with path.open(encoding='utf-8') as f: return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser(); p.add_argument('results',type=Path); a=p.parse_args()
    root=a.results; out=root/'figures'; out.mkdir(exist_ok=True)
    runs=load(root/'runs.csv'); dist=load(root/'distributions.csv')
    traces=load(root/'first-repeat-traces.csv'); windows=load(root/'windows.csv')
    colors={'01':'#0072B2','05':'#D55E00','07':'#009E73'}
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':170})
    def save(fig,name):
        fig.savefig(out/(name+'.png'),bbox_inches='tight')
        fig.savefig(out/(name+'.pdf'),bbox_inches='tight'); plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(14,4))
    for ax,mode,metric,title in zip(axes,['upstream','periodic','periodic'],
            ['call_ms','call_ms','delay_ms'],['A: TrackStereo call','B: TrackStereo call','B: release to pose return']):
        for seq,color in colors.items():
            labeled=False
            for rep in range(1,6):
                d=[r for r in dist if r['mode']==mode and r['sequence']==seq and int(r['repeat'])==rep and r['metric']==metric and float(r['percentile'])<100]
                if not d: continue
                x=np.array([float(r['value']) for r in d]); y=1-np.array([float(r['percentile']) for r in d])/100
                ax.plot(x,y,color=color,alpha=.55,lw=1,label=f'Sequence {seq}' if not labeled else None)
                labeled=True
        ax.set(xscale='log',yscale='log',xlabel='Milliseconds',ylabel='Fraction exceeding threshold',title=title)
        ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.suptitle('Native KITTI timing: completed runs from five planned process repeats')
    fig.tight_layout(); save(fig,'latency-distributions')
    fig,axes=plt.subplots(3,1,figsize=(12,8))
    for ax,seq in zip(axes,colors):
        d=[r for r in traces if r['sequence']==seq and r['mode']=='periodic']
        if not d: continue
        t=[float(r['dataset_s']) for r in d]
        for key,label,color in [('service_ms','Service','#0072B2'),('delay_ms','Release to return','#D55E00')]:
            ax.plot(t,[float(r[key]) for r in d],label=label,color=color,lw=.75)
        bad=[r for r in d if int(r['state'])!=2]
        if bad: ax.scatter([float(r['dataset_s']) for r in bad],[1]*len(bad),color='black',s=5,label='Tracking state not OK')
        ax.axhline(100,color='grey',ls=':',label='100 ms reference')
        incomplete=d[0].get('run_status')!='completed'
        if incomplete:
            ax.axvspan(t[-1],float(d[0]['planned_end_s']),color='grey',alpha=.2,label='Unrecorded after saved prefix')
        ax.set(yscale='log',ylabel='Milliseconds',title=f'Sequence {seq}: preselected first repeat'+(' (aborted; prefix only)' if incomplete else ''))
        ax.grid(alpha=.2); ax.legend(fontsize=8,ncol=4)
    axes[-1].set_xlabel('Dataset time (seconds)'); fig.tight_layout(); save(fig,'periodic-time-series')
    fig,axes=plt.subplots(1,3,figsize=(14,4),sharey=True)
    for ax,deadline in zip(axes,[100,200,500]):
        for seq,color in colors.items():
            labeled=False
            for rep in range(1,6):
                d=[r for r in windows if r['sequence']==seq and int(r['repeat'])==rep and int(r['deadline_ms'])==deadline]
                if not d: continue
                ax.plot([int(r['H']) for r in d],[float(r['timely_rate']) for r in d],'-o',ms=3,color=color,alpha=.5,label=f'{seq}: timely' if not labeled else None)
                ax.plot([int(r['H']) for r in d],[float(r['timely_valid_rate']) for r in d],':',color=color,alpha=.6,label=f'{seq}: timely + valid' if not labeled else None)
                labeled=True
        ax.set(title=f'Deadline {deadline} ms',xlabel='Window length (frames)',ylim=(-.03,1.03),xticks=[1,5,10,20])
        ax.grid(alpha=.2)
    axes[0].set_ylabel('Window success rate\n(complete runs only)'); axes[-1].legend(fontsize=7)
    fig.tight_layout(); save(fig,'window-reliability')
    fig,axes=plt.subplots(1,3,figsize=(14,4))
    for mi,(metric,title) in enumerate([('call_ms_p99','TrackStereo p99 (ms)'),('valid_fraction','Tracking-valid fraction'),('whole_ate_rmse_m','Online ATE RMSE (m), rigid alignment')]):
        ax=axes[mi]
        for j,(mode,seq) in enumerate((m,s) for m in ['upstream','periodic'] for s in colors):
            selected=[r for r in runs if r['mode']==mode and r['sequence']==seq and r['status']=='completed' and r.get(metric)]
            vals=[float(r[metric]) for r in selected]
            if vals:
                ax.scatter(np.arange(len(vals))*.05+j-.1,vals,color=colors[seq],s=22)
                ax.plot([j-.18,j+.18],[np.median(vals)]*2,color='black',lw=1)
        ax.set(xticks=range(6),xticklabels=['A01','A05','A07','B01','B05','B07'],title=title)
        ax.grid(axis='y',alpha=.2)
        if mi!=1: ax.set_yscale('log')
        else: ax.set_ylim(-.02,1.02)
    fig.suptitle('Completed repeats and quality; each dot is a process run, bars are medians')
    fig.tight_layout(); save(fig,'repeat-quality')


if __name__=='__main__': main()
