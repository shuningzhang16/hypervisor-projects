#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
output=${1:-"runs/offline-$(date -u +%Y%m%dT%H%M%SZ)-$$"}
mkdir -p "$(dirname "$output")"
mkdir "$output"
exec > >(tee "$output/tests.log") 2>&1
trap 'rc=$?; printf "exit_code=%s\n" "$rc" > "$output/status.txt"' EXIT
uname -a
python3 --version
gcc --version | head -1
bash -n kvm_exit_analyzer/check_host.sh kvm_exit_analyzer/collect_kvm_trace.sh scripts/build_linux_guest.sh scripts/build_qemu.sh
python3 -m unittest discover -s kvm_exit_analyzer/tests -v
python3 kvm_exit_analyzer/analyze_trace.py kvm_exit_analyzer/tests/fixtures/synthetic_trace.txt --out "$output/synthetic-report" --source-kind synthetic
gcc -std=c11 -Wall -Wextra -Werror -g -fsanitize=address,undefined \
    -I qemu_virtio_lab qemu_virtio_lab/lab-protocol.c qemu_virtio_lab/tests/test_protocol.c \
    -o "$output/test_protocol"
"$output/test_protocol"
gcc -std=c11 -O2 -Wall -Wextra -Werror -pthread kvm_exit_analyzer/workloads/kvm_microbench.c -o "$output/kvm_microbench"
gcc -std=c11 -O2 -Wall -Wextra -Werror -pthread kvm_exit_analyzer/workloads/linux_guest_workload.c -o "$output/linux_guest_workload"
gcc -std=c11 -O2 -Wall -Wextra -Werror kvm_exit_analyzer/workloads/perf_tid_map.c -o "$output/perf_tid_map"
echo 'PASS: offline tests only; no real VM/KVM benchmark performed.'
