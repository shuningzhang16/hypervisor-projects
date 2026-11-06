#!/usr/bin/env bash
# Builds an isolated QEMU tree; never installs into the system.
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
destination=${1:-"$project/build/qemu"}
mkdir -p "$destination"
destination=$(cd "$destination" && pwd)
version=$(cat "$project/qemu_virtio_lab/QEMU_VERSION")
exec > >(tee "$destination/build-$(date -u +%Y%m%dT%H%M%SZ)-$$.log") 2>&1
if [[ ! -d $destination/qemu-$version ]]; then
    curl --fail --location "https://download.qemu.org/qemu-$version.tar.xz" -o "$destination/qemu-$version.tar.xz"
    tar -xf "$destination/qemu-$version.tar.xz" -C "$destination"
fi
python3 -m venv --system-site-packages "$destination/tools-venv"
"$destination/tools-venv/bin/pip" install 'tomli>=1.2' 'meson==1.5.0' 'pycotap==1.3.1'
python3 "$project/qemu_virtio_lab/integrate.py" "$destination/qemu-$version"
mkdir -p "$destination/qemu-$version/build"
cd "$destination/qemu-$version/build"
../configure --python="$destination/tools-venv/bin/python" --target-list=x86_64-softmmu \
    --disable-docs --disable-gtk --disable-sdl --disable-vnc --enable-trace-backends=log
ninja -j "${JOBS:-4}" qemu-system-x86_64
./qemu-system-x86_64 --version
