"""Fetch one nested EuRoC ZIP from ETH's official archive using validated ranges.

No full parent download. --inspect only reads ZIP metadata; existing files are
never overwritten. HTTPS transport and archive CRC are checked; a newly measured
SHA256 is an identity record, not an independently published authenticity hash.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import time
import urllib.error
import urllib.request
import zipfile
import zlib

URL = 'https://www.research-collection.ethz.ch/server/api/core/bitstreams/02ecda9a-298f-498b-970c-b7c44334d880/content'
TOTAL = 6042263426


def ranged(start, end):
    for attempt in range(3):
        req = urllib.request.Request(URL, headers={
            'User-Agent': 'ORB-SLAM3-research/1.0', 'Range': f'bytes={start}-{end}',
            'Accept-Encoding': 'identity'})
        try:
            response = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < 2:
                value = exc.headers.get('Retry-After', '30')
                delay = max(30, int(value)) if value.isdigit() else 60
                if delay > 60:
                    raise
                print('Server requested backoff:', delay, flush=True)
                time.sleep(delay)
                continue
            raise
        if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{TOTAL}':
            response.close()
            raise ValueError('Server did not honor the exact requested byte range')
        return response
    raise RuntimeError('No HTTP response')


class RemoteZIP(io.RawIOBase):
    def __init__(self):
        self.position = 0

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else TOTAL + offset
        return self.position

    def read(self, size=-1):
        size = TOTAL - self.position if size < 0 else min(size, TOTAL-self.position)
        if size <= 0:
            return b''
        if size > 8*1024*1024:
            raise ValueError('Unexpectedly large central directory request')
        with ranged(self.position, self.position+size-1) as response:
            data = response.read()
        if len(data) != size:
            raise ValueError('Truncated metadata range')
        self.position += size
        return data



def ensure_storage_budget(root, additional, budget):
    """Count existing payloads plus the conservative next write; no deletions."""
    if budget is None:
        return
    if budget <= 0 or additional < 0:
        raise ValueError('Storage budget must be positive and addition nonnegative')
    used = sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())
    if used + additional > budget:
        raise ValueError(f'Data storage budget exceeded: {used} + {additional} > {budget}')


def main():
    global URL, TOTAL
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sequence', choices=['V1_01_easy', 'V1_02_medium', 'V1_03_difficult', 'V2_01_easy', 'V2_02_medium', 'V2_03_difficult', 'MH_01_easy', 'MH_03_medium'], required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--storage-budget-bytes', type=int, help='Total retained logical bytes in output data directory')
    a = p.parse_args()
    room='machine_hall' if a.sequence.startswith('MH_') else 'vicon_room2' if a.sequence.startswith('V2_') else 'vicon_room1'
    sources={
        'vicon_room1':('02ecda9a-298f-498b-970c-b7c44334d880',6042263426),
        'vicon_room2':('ea12bc01-3677-4b4c-853d-87c7870b8c44',6013384949),
        'machine_hall':('7b2419c1-62b5-4714-b7f8-485e5fe3e5fe',12683729426)}
    identifier,TOTAL=sources[room]
    URL='https://www.research-collection.ethz.ch/server/api/core/bitstreams/'+identifier+'/content'
    member = f'{room}/{a.sequence}/{a.sequence}.zip'
    with zipfile.ZipFile(RemoteZIP()) as remote:
        info = remote.getinfo(member)
    entry = dict(name=member, bytes=info.file_size, compressed=info.compress_size,
                 offset=info.header_offset, CRC32=info.CRC, compression=info.compress_type)
    print(json.dumps(entry, indent=2), flush=True)
    if a.inspect:
        return
    root = a.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    archive = root/(a.sequence+'.zip')
    partial = root/(a.sequence+'.zip.partial')
    target = root/a.sequence
    manifest = root/(a.sequence+'-manifest.json')
    if any(f.exists() for f in (archive, partial, target, manifest)):
        raise ValueError('Refusing to overwrite existing data')
    ensure_storage_budget(root, 5*info.file_size, a.storage_budget_bytes)
    if shutil.disk_usage(root).free < 5*info.file_size:
        raise ValueError('Insufficient free space for conservative extraction budget')
    with ranged(info.header_offset, info.header_offset+4095) as response:
        header = response.read()
    parts = struct.unpack('<4s5H3I2H', header[:30])
    name_size, extra_size = parts[-2:]
    if parts[0] != b'PK\x03\x04' or parts[3] != 8 or parts[2] & 1 or header[30:30+name_size].decode() != member:
        raise ValueError('Unsupported/mismatched nested ZIP header')
    start = info.header_offset+30+name_size+extra_size
    decoder = zlib.decompressobj(-15)
    crc = size = consumed = 0
    digest = hashlib.sha256()
    began = last = time.monotonic()
    with ranged(start, start+info.compress_size-1) as response, partial.open('xb') as output:
        headers = dict(response.headers)
        while chunk := response.read(1024*1024):
            consumed += len(chunk)
            data = decoder.decompress(chunk)
            output.write(data)
            crc = zlib.crc32(data, crc)
            digest.update(data)
            size += len(data)
            if time.monotonic()-last > 20:
                print('Downloaded MiB:', round(consumed/2**20), '/', round(info.compress_size/2**20), flush=True)
                last = time.monotonic()
        data = decoder.flush()
        output.write(data)
        crc = zlib.crc32(data, crc)
        digest.update(data)
        size += len(data)
    if not decoder.eof or decoder.unused_data or consumed != info.compress_size or size != info.file_size or crc != info.CRC:
        raise ValueError('Nested ZIP size/CRC/decompression check failed; partial retained')
    partial.rename(archive)
    target.mkdir()
    with zipfile.ZipFile(archive) as z:
        expanded = sum(i.file_size for i in z.infolist())
        ensure_storage_budget(root, expanded, a.storage_budget_bytes)
        if expanded > 4*info.file_size or expanded > shutil.disk_usage(root).free:
            raise ValueError('Expansion budget exceeded')
        for item in z.infolist():
            path = (target/item.filename).resolve()
            if not path.is_relative_to(target) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe ZIP path')
        z.extractall(target)  # ZipExtFile checks each extracted member's CRC.
    frame_sets = {cam:{p.stem for p in (target/'mav0'/cam/'data').glob('*.png')} for cam in ('cam0','cam1')}
    frames = {cam:len(s) for cam,s in frame_sets.items()}
    common = frame_sets['cam0'] & frame_sets['cam1']
    if len(common) < 100:
        raise ValueError('Insufficient paired stereo frames')
    record = dict(source=URL, parent_name=room+'.zip', parent_size=TOTAL,
                  parent_MD5_not_verified='Only selected member downloaded', member=entry,
                  download_range=[start,start+info.compress_size-1], download_headers=headers,
                  member_CRC32_verified=True, inner_CRC32_verified=True, sha256=digest.hexdigest(),
                  sha256_scope='Measured identity; no independently published expected SHA256',
                  storage_budget_bytes=a.storage_budget_bytes,
                  zip_bytes=size, expanded_bytes=expanded, seconds=time.monotonic()-began, frames=frames,
                  paired_frames=len(common), unpaired_frames={cam:sorted(s-common) for cam,s in frame_sets.items()},
                  license='In Copyright - Non-Commercial Use Permitted', DOI='10.3929/ethz-b-000690084')
    manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,indent=2),flush=True)


if __name__ == '__main__':
    main()
