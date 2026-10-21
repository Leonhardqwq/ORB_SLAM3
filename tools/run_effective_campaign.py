"""Serially execute frozen E3 profiles; preserve a failed profile and stop there."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('design','source','data-root','output','reference','e2-result','companion'):
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    tools=Path(__file__).resolve().parent
    design=json.loads(a.design.read_text())
    a.output.mkdir(parents=True,exist_ok=False)
    records=[]
    for cfg in design['profiles_in_order']:
        out=a.output/cfg['id']
        protocol=a.design.parent/cfg['protocol']
        if hashlib.sha256(protocol.read_bytes()).hexdigest()!=cfg['protocol_sha256']:
            raise ValueError('protocol differs from frozen design: '+cfg['id'])
        cmd=[sys.executable,str(tools/'run_effective_collection.py'),'--source',str(a.source),
             '--data',str(a.data_root/cfg['sequence']),'--output',str(out),
             '--protocol',str(protocol),'--reference',str(a.reference),
             '--e2-result',str(a.e2_result),'--companion',str(a.companion)]
        print('Starting profile',cfg['id'],flush=True)
        done=subprocess.run(cmd)
        record={'id':cfg['id'],'command':cmd,'returncode':done.returncode}
        records.append(record)
        if (out/'result.json').exists():
            record['result']=json.loads((out/'result.json').read_text())
            summarize=subprocess.run([sys.executable,str(tools/'summarize_effective_collection.py'),
                                      '--collection',str(out),'--output',str(a.output/(cfg['id']+'-summary.json'))])
            record['summary_returncode']=summarize.returncode
        (a.output/'campaign.json').write_text(json.dumps(records,indent=2)+'\n')
        if done.returncode or record.get('summary_returncode',1):
            print('Profile requires diagnosis; later profiles not executed:',cfg['id'],flush=True)
            return 1
    return 0

if __name__=='__main__':
    raise SystemExit(main())
