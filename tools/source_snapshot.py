"""Export current build inputs, or unpack/verify a self-generated snapshot.

Source files are never rewritten. Existing outputs are never overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

p = argparse.ArgumentParser(description=__doc__)
sub = p.add_subparsers(dest='action', required=True)
pack = sub.add_parser('pack')
pack.add_argument('--source', type=Path, required=True)
pack.add_argument('--output', type=Path, required=True)
unpack = sub.add_parser('unpack')
unpack.add_argument('--archive', type=Path, required=True)
unpack.add_argument('--manifest', type=Path, required=True)
unpack.add_argument('--destination', type=Path, required=True)
a = p.parse_args()
if a.action == 'pack':
    root = a.source.resolve()
    git = ['git', '--no-optional-locks', '-c', 'safe.directory=' + root.as_posix(), '-C', str(root)]
    def git_read(*args):
        return subprocess.check_output(git + list(args)).decode('utf-8')
    # Include selected new build inputs without staging them. Ignore rules apply.
    names = sorted(set(filter(None, git_read('ls-files', '--cached', '--others', '--exclude-standard', '-z').split('\0'))))
    files = {}
    for name in names:
        path = PurePosixPath(name)
        if not (path.parts[0] in {'src', 'include', 'Thirdparty', 'Examples', 'Examples_old', 'Vocabulary', 'evaluation'}
                or name in {'CMakeLists.txt', 'build.sh', 'README.md', 'LICENSE', 'License-gpl.txt', 'License-bsd.txt'}):
            continue
        if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.pdf', '.tif', '.tiff'} or any(
                part in path.parts for part in ('TUM_IMU', 'EuRoC_IMU', 'Ground_truth')):
            continue
        source = root / name
        if not source.exists():  # Current worktree deletion, never resurrect the index version.
            continue
        if source.is_symlink() or not source.is_file():
            raise ValueError('Unsupported input: ' + name)
        files[name] = {'bytes': source.stat().st_size, 'sha256': sha(source)}
    assert 'CMakeLists.txt' in files and 'src/System.cc' in files
    a.output.mkdir(parents=True, exist_ok=False)
    archive = a.output / 'source.tar'
    with tarfile.open(archive, 'x') as tar:
        for name in files:
            tar.add(root / name, arcname=name, recursive=False)
    manifest = {'head': git_read('rev-parse', 'HEAD').strip(),
                'branch': git_read('branch', '--show-current').strip(),
                'status': git_read('status', '--short'),
                'files': files, 'archive_sha256': sha(archive),
                'selection': 'Current tracked and unignored new build inputs; exclude image/PDF and inertial sample data'}
    (a.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'files': len(files), 'bytes': archive.stat().st_size, 'head': manifest['head']}))
else:
    manifest = json.loads(a.manifest.read_text(encoding='utf-8'))
    assert sha(a.archive) == manifest['archive_sha256'], 'Archive hash mismatch'
    dest = a.destination.resolve()
    assert not dest.exists(), 'Use a new destination; never overwrite a worktree'
    with tarfile.open(a.archive) as tar:
        members = tar.getmembers()
        assert len(members) == len(manifest['files'])
        assert {m.name for m in members} == set(manifest['files'])
        for member in members:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and '..' not in path.parts
        dest.mkdir(parents=True)
        for member in members:
            path = dest / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, path.open('xb') as out:
                out.write(source.read())
            assert sha(path) == manifest['files'][member.name]['sha256'], member.name
    print(json.dumps({'verified_files': len(members), 'destination': str(dest)}))
