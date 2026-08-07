#!/bin/sh
# Emulation boundary (design-deployment.md): only the SC2 binary runs under
# amd64 emulation — whole-container Rosetta crashes it at port initialization
# (impl-deployment.md). exec keeps the process id burnysc2 kills.
here="$(dirname "$(readlink -f "$0")")"
if [ "$(uname -m)" = x86_64 ]; then
    exec "$here/SC2_x64.real" "$@"
fi
exec qemu-x86_64 "$here/SC2_x64.real" "$@"
