#!/bin/sh
# Developer/CI helper; Python is only needed to build bundles, never to install them.
set -eu
exec python3 "$(dirname "$0")/package.py" "$@"
