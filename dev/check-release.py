"""Check version consistency and shipped skill/site references without a robot."""
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import unquote

root = Path(__file__).resolve().parents[1]
version = (root / 'VERSION').read_text().strip()
assert re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?', version)
assert tomllib.loads((root / 'cli/vexaim/Cargo.toml').read_text())['package']['version'] == version
tag = os.environ.get('GITHUB_REF', '')
if tag.startswith('refs/tags/'):
    assert tag == f'refs/tags/v{version}', 'tag and source version differ'
skill = root / 'skill/vex-aim'
text = (skill / 'SKILL.md').read_text()
assert text.startswith('---\nname: vex-aim\n')
assert 'description:' in text.split('---', 2)[1]
assert '90-minute' not in text and 'references/workshop.md' not in text
for name in re.findall(r'`(references/[^`]+\.md)`', text):
    assert (skill / name).is_file(), f'missing skill reference: {name}'
for page in list((root / 'site').glob('*.html')) + [root / 'README.md']:
    for target in re.findall(r'(?:href|src)="([^"]+)"|\]\(([^)]+)\)', page.read_text()):
        link = next(x for x in target if x).split('#')[0]
        if not link or ':' in link or link.startswith('/'):
            continue
        assert (page.parent / unquote(link)).exists(), f'broken local link: {page}: {link}'
html = (root / 'site/index.html').read_text()
for target, extension in [('windows-x86_64','zip'),('linux-x86_64','tar.gz'),('macos-arm64','tar.gz'),('macos-x86_64','tar.gz')]:
    assert f'releases/latest/download/vexaim-{target}.{extension}' in html
print(f'Release inputs, basic skill and site links valid: {version}')
