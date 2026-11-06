#!/usr/bin/env bash
# Local evidence run; Guest-only module loading is performed by its /init.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
project=$(cd "$(dirname "$0")/.." && pwd)
output=/var/tmp/hypervisor-driver-evidence
assets=/var/tmp/hypervisor-driver-build-ready
qemu=/var/tmp/hypervisor-build.0923va/qemu-9.2.0/build/qemu-system-x86_64
bash "$project/scripts/build_guest_driver.sh" /var/tmp/hypervisor-driver-kernel/root "$assets"
python3 -u "$project/qemu_virtio_lab/tests/guest_driver.py" --qemu "$qemu" --assets "$assets" \
    --out "$output/kvm-split-ready" --samples 1000 --cycles 8 2>&1 | tee "$output/kvm-split-ready.console"
python3 -u "$project/qemu_virtio_lab/tests/guest_driver.py" --qemu "$qemu" --assets "$assets" \
    --out "$output/kvm-packed-ready" --packed --samples 1000 --cycles 8 2>&1 | tee "$output/kvm-packed-ready.console"
python3 -u "$project/qemu_virtio_lab/tests/guest_driver.py" --qemu "$qemu" --assets "$assets" \
    --out "$output/tcg-packed-smoke" --accelerator tcg --packed --smoke-only 2>&1 | tee "$output/tcg-packed-smoke.console"
