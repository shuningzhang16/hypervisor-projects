#!/usr/bin/env bash
# This host's evidence run, not a portable dependency installer.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
root=$(cd "$(dirname "$0")/.." && pwd)
out=/var/tmp/hypervisor-phase3-evidence
qemu=/var/tmp/hypervisor-build.0923va/qemu-9.2.0/build/qemu-system-x86_64
cd "$root"
python3 kvm_exit_analyzer/summarize_linux_matrix.py "$out/linux-matrix" --out "$out/linux-report" 2>&1 | tee "$out/summarize.console"
python3 qemu_virtio_lab/tests/qtest_packed.py "$qemu" --out "$out/packed" 2>&1 | tee "$out/packed.console"
bash scripts/build_linux_guest.sh '/mnt/c/Program Files/WSL/tools/kernel' \
    /lib/modules/6.6.114.1-microsoft-standard-WSL2 /var/tmp/hypervisor-guest-phase3-hotplug
python3 qemu_virtio_lab/tests/qmp_hotplug.py --qemu "$qemu" \
    --assets /var/tmp/hypervisor-guest-phase3-hotplug --out "$out/hotplug" --cycles 32 2>&1 | tee "$out/hotplug.console"
bash run_offline_tests.sh "$out/offline" 2>&1 | tee "$out/offline.console"
python3 qemu_virtio_lab/tests/qtest_soak.py "$qemu" --out "$out/soak" --seconds 600 2>&1 | tee "$out/soak.console"
