"""Check the actual PE imports, so students need no Visual C++ runtime installer.

Developer/CI dependency only: pefile==2024.8.26. Never needed by student installs.
"""
import re
import sys
import pefile

with pefile.PE(sys.argv[1], fast_load=True) as image:
    image.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT'],
    ])
    imports = {item.dll.decode('ascii').lower() for directory in
               ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
               for item in getattr(image, directory, [])}
for name in sorted(imports):
    if re.match(r'^(?:vcruntime|msvcp|msvcr)\d.*\.dll$', name):
        raise SystemExit(f'Nonportable Windows binary: requires {name}; build with static CRT')
print(f'Windows portability check passed ({len(imports)} OS imports, no Visual C++ runtime DLLs)')
