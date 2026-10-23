#!/usr/bin/env python3
"""Package one native executable with its matching skill, installer and notices."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

def package(target, binary, output):
    repo = Path(__file__).resolve().parents[1]
    version = (repo / 'VERSION').read_text().strip()
    actual = subprocess.check_output([str(Path(binary).resolve()), '--version'], text=True).strip()
    if actual != f'vexaim {version}':
        raise SystemExit(f'version mismatch: expected {version}, got {actual}')
    targets = {'windows-x86_64', 'linux-x86_64', 'macos-arm64', 'macos-x86_64'}
    if target not in targets:
        raise SystemExit(f'unsupported release target: {target}')
    windows = target.startswith('windows-')
    files = [(Path(binary), 'vexaim.exe' if windows else 'vexaim')]
    files += [(repo / name, name) for name in ('VERSION', 'install.sh', 'install.ps1', 'LICENSE', 'NOTICE.md')]
    files += [(p, p.relative_to(repo).as_posix()) for p in sorted((repo / 'skill').rglob('*'))
              if p.is_file() and p.suffix in ('.md', '.sh', '.ps1', '.rules')]
    for name in ('LICENSE-vex-v5-serial-MIT', 'btleplug/LICENSE', 'btleplug/LICENSE.md'):
        path = repo / 'cli/vendor' / name
        if path.is_file():
            files.append((path, 'licenses/' + name.replace('/', '-')))
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    archive = out / f'vexaim-{target}{".zip" if windows else ".tar.gz"}'
    if windows:
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for source, name in files:
                bundle.write(source, name)
    else:
        with tarfile.open(archive, 'w:gz') as bundle:
            for source, name in files:
                bundle.add(source, arcname=name, recursive=False)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / 'SHA256SUMS').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'Packaged {archive}: executable and skill {version}')

if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('usage: package.py TARGET BINARY OUTPUT')
    package(*sys.argv[1:])
