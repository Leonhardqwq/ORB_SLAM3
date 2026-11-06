"""Fetch selected members of the official public KITTI ZIP using HTTP ranges."""
import argparse
import hashlib
import io
import json
import struct
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = 'https://avg-kitti.s3.eu-central-1.amazonaws.com/'


def fetch(url, start=None, end=None):
    headers = {} if start is None else {'Range': f'bytes={start}-{end}'}
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
                if start is not None and r.status != 206:
                    raise RuntimeError('Server did not honor partial request')
                data, meta = r.read(), dict(r.headers)
            if start is not None and len(data) != end-start+1:
                raise RuntimeError('Incomplete byte range')
            return data, meta
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--sequences', nargs='+', default=['01', '05', '07'])
    ap.add_argument('--workers', type=int, default=12)
    a = ap.parse_args()
    root = a.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    url = BASE + 'data_odometry_gray.zip'
    with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=60) as r:
        size = int(r.headers['Content-Length'])
        etag = r.headers.get('ETag')
    sparse = root / '.selected-gray.sparse.zip'
    if not sparse.exists():
        tail_start = size-65536
        tail, _ = fetch(url, tail_start, size-1)
        eocd = tail.rfind(b'PK\x05\x06')
        locator = eocd-20
        zip64_offset = struct.unpack_from('<Q', tail, locator+8)[0]
        zip64, _ = fetch(url, zip64_offset, zip64_offset+55)
        cdsize, cdoffset = struct.unpack_from('<QQ', zip64, 40)
        directory, _ = fetch(url, cdoffset, cdoffset+cdsize-1)
        # Sparse on WSL ext4; not a full 23 GB download.
        with sparse.open('wb') as f:
            f.truncate(size)
            f.seek(tail_start); f.write(tail)
            f.seek(cdoffset); f.write(directory)
    with zipfile.ZipFile(sparse) as z:
        infos = sorted(z.infolist(), key=lambda x: x.header_offset)
        cdoffset = z.start_dir
    selected = []
    spans = []
    for i, entry in enumerate(infos):
        p = entry.filename.split('/')
        if (len(p) >= 4 and p[:2] == ['dataset', 'sequences'] and p[2] in a.sequences
                and (p[3] in ['image_0', 'image_1', 'times.txt']) and not entry.is_dir()):
            selected.append(entry)
            end = infos[i+1].header_offset if i+1 < len(infos) else cdoffset
            if spans and entry.header_offset-spans[-1][1] < 4096:
                spans[-1][1] = end
            else:
                spans.append([entry.header_offset, end])
    total = sum(y-x for x, y in spans)
    print(json.dumps({'members': len(selected), 'download_bytes': total, 'ranges': len(spans)}), flush=True)
    checkpoint = root/'.selected-ranges.json'
    completed = set(json.loads(checkpoint.read_text())) if checkpoint.exists() else set()
    chunks = [(start, min(start+4*1024*1024, hi)-1) for lo,hi in spans
              for start in range(lo,hi,4*1024*1024)]
    done = sum(end-start+1 for start,end in chunks if str(start) in completed)
    with sparse.open('r+b') as f:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            pending = {pool.submit(fetch,url,start,end):(start,end) for start,end in chunks if str(start) not in completed}
            for future in as_completed(pending):
                start,end=pending[future]
                chunk, _ = future.result()
                f.seek(start)
                f.write(chunk)
                f.flush()
                done += len(chunk)
                completed.add(str(start))
                checkpoint.write_text(json.dumps(sorted(completed)))
                print(f'download {done}/{total} ({100*done/total:.1f}%)', flush=True)
    records = []
    with zipfile.ZipFile(sparse) as z:
        for n, entry in enumerate(selected):
            dest = root.joinpath(*Path(entry.filename).parts[1:])
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = z.read(entry)  # zipfile checks the selected member CRC.
            dest.write_bytes(data)
            records.append({'path': str(dest.relative_to(root)), 'bytes': len(data),
                            'crc32': f'{entry.CRC:08x}', 'sha256': hashlib.sha256(data).hexdigest()})
            if n % 1000 == 0:
                print(f'extract {n}/{len(selected)}', flush=True)
    sparse.unlink()
    checkpoint.unlink()
    sources = [{'url': url, 'etag': etag, 'archive_bytes': size,
                'selected_transfer_bytes': total, 'verification': 'selected member CRC + local SHA256'}]
    for name in ['data_odometry_calib.zip', 'data_odometry_poses.zip']:
        data, meta = fetch(BASE+name)
        sources.append({'url': BASE+name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for entry in z.infolist():
                parts = Path(entry.filename).parts
                wanted = (len(parts) >= 4 and parts[1] == 'sequences' and parts[2] in a.sequences)
                wanted |= (len(parts) == 3 and parts[1] == 'poses' and Path(parts[2]).stem in a.sequences)
                if wanted and not entry.is_dir():
                    dest = root.joinpath(*parts[1:])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    payload = z.read(entry)
                    if dest.exists() and dest.read_bytes() != payload:
                        raise RuntimeError(f'Conflicting archive member {dest}')
                    dest.write_bytes(payload)
                    records.append({'path': str(dest.relative_to(root)), 'bytes': len(payload),
                                    'sha256': hashlib.sha256(payload).hexdigest()})
    counts = {}
    for seq in a.sequences:
        sd = root/'sequences'/seq
        counts[seq] = {k: len(list((sd/k).glob('*.png'))) for k in ['image_0', 'image_1']}
        counts[seq]['timestamps'] = len((sd/'times.txt').read_text().splitlines())
        counts[seq]['poses'] = len((root/'poses'/f'{seq}.txt').read_text().splitlines())
        if len(set(counts[seq].values())) != 1:
            raise RuntimeError(f'Frame counts disagree: {counts[seq]}')
    manifest = {'sources': sources, 'counts': counts, 'files': records}
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (root/'summary.json').write_text(json.dumps({'sources': sources, 'counts': counts,
        'manifest_sha256': hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()}, indent=2)+'\n')
    print(json.dumps(counts), flush=True)


if __name__ == '__main__':
    main()
