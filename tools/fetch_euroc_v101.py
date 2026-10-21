from pathlib import Path
import urllib.request,urllib.error,json,time,struct,zlib,hashlib,zipfile
import argparse
p=argparse.ArgumentParser(description="Download only V1_01_easy from the official EuRoC archive")
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
root=a.output.resolve()
root.mkdir(parents=True,exist_ok=True)
entry={'name':'vicon_room1/V1_01_easy/V1_01_easy.zip',
       'bytes':1149702102,'compressed':1149535352,'offset':1540401879,
       'CRC32':448686605,'compression':8}
url='https://www.research-collection.ethz.ch/server/api/core/bitstreams/02ecda9a-298f-498b-970c-b7c44334d880/content'
total=6042263426
def ranged(start,end):
    for attempt in range(3):
        req=urllib.request.Request(url,headers={'User-Agent':'ORB-SLAM3-environment-check/1.0','Range':f'bytes={start}-{end}','Accept-Encoding':'identity'})
        try:r=urllib.request.urlopen(req,timeout=60)
        except urllib.error.HTTPError as e:
            if e.code==429 and attempt<2:
                retry=e.headers.get('Retry-After','30')
                delay=max(30,int(retry)) if retry.isdigit() else 60
                if delay>60:raise
                print('HTTP 429; wait',delay,'seconds',flush=True);time.sleep(delay);continue
            raise
        assert r.status==206,(r.status,'Range required')
        assert r.headers.get('Content-Range')==f'bytes {start}-{end}/{total}',r.headers.get('Content-Range')
        return r
    raise RuntimeError('No response')
start=entry['offset']
with ranged(start,start+4095) as r:header=r.read(4096)
parts=struct.unpack('<4s5H3I2H',header[:30])
assert parts[0]==b'PK\x03\x04' and parts[3]==8 and not parts[2]&1
name_size,extra_size=parts[-2:]
assert header[30:30+name_size].decode()==entry['name']
data_start=start+30+name_size+extra_size
data_end=data_start+entry['compressed']-1
archive=root/'V1_01_easy.zip';partial=root/'V1_01_easy.zip.partial'
assert not archive.exists() and not partial.exists(),'preserve existing data; inspect before retry'
decoder=zlib.decompressobj(-15);crc=0;sha=hashlib.sha256();output_size=0;read_size=0
t=time.monotonic();last=t
with ranged(data_start,data_end) as response,partial.open('xb') as out:
    headers=dict(response.headers)
    while chunk:=response.read(1024*1024):
        read_size+=len(chunk);data=decoder.decompress(chunk)
        out.write(data);crc=zlib.crc32(data,crc);sha.update(data);output_size+=len(data)
        if time.monotonic()-last>20:
            print('Downloaded',round(read_size/2**20),'/',round(entry['compressed']/2**20),'MiB',flush=True);last=time.monotonic()
    data=decoder.flush();out.write(data);crc=zlib.crc32(data,crc);sha.update(data);output_size+=len(data)
assert decoder.eof and not decoder.unused_data
assert read_size==entry['compressed'] and output_size==entry['bytes']
assert crc==entry['CRC32'],('Outer ZIP member CRC mismatch',crc,entry['CRC32'])
assert sha.hexdigest()=='a920fe5b5e69a6ad19b32f1cfaf90ac2f59d45dfd1ca18cc9722e07684ba45fa', 'Pinned member SHA256 mismatch'
partial.rename(archive)
target=root/'V1_01_easy';assert not target.exists();target.mkdir()
with zipfile.ZipFile(archive) as z:
    for i in z.infolist():
        p=(target/i.filename).resolve()
        assert p.is_relative_to(target.resolve()) and (i.external_attr>>16)&0o170000 != 0o120000
    z.extractall(target)
cams={cam:len(list((target/'mav0'/cam/'data').glob('*.png'))) for cam in ['cam0','cam1']}
assert cams['cam0']==cams['cam1'] and cams['cam0']>100
record={'source':url,'parent_name':'vicon_room1.zip','parent_size':total,'parent_MD5_not_verified':'Only selected ZIP member downloaded','member':entry,'download_range':[data_start,data_end],'download_bytes':read_size,'download_headers':headers,'member_CRC32_verified':True,'sha256':sha.hexdigest(),'zip_bytes':output_size,'seconds':time.monotonic()-t,'frames':cams,'license':'In Copyright - Non-Commercial Use Permitted','DOI':'10.3929/ethz-b-000690084'}
(root/'V1_01_easy-manifest.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record,indent=2),flush=True)
