#!/usr/bin/env bash
# Batch mode: upscales the images in /input into /output with the app's own engine; add --help for the options.
set -euo pipefail
# The only thing running, so every core works and none is kept free for a desktop
CORES="$(nproc)"
export CPU_CORES_RESERVED=0 OMP_NUM_THREADS="$CORES" MKL_NUM_THREADS="$CORES"
exec python /srv/web/batch.py --input /input --output /output "$@"
