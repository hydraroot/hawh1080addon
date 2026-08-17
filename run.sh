#!/bin/sh
set -eu

echo "=========================================="
echo " WH1080 USB WEATHER STATION"
echo "=========================================="

python --version

exec python /wh1080.py