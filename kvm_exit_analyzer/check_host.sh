#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    echo 'ERROR: requires x86-64 Linux' >&2
    exit 1
fi
echo "kernel=$(uname -r)"
echo "cpu=$(sed -n '/^model name/{s/.*: //;p;q;}' /proc/cpuinfo)"
status=0
if [[ -c /dev/kvm ]]; then
    ls -l /dev/kvm
    if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then
        echo 'ERROR: current user cannot read/write /dev/kvm' >&2
        status=1
    else
        python3 - <<'PY'
import fcntl, os
try:
    fd = os.open('/dev/kvm', os.O_RDWR | os.O_CLOEXEC)
    try:
        api = fcntl.ioctl(fd, 0xAE00, 0)  # KVM_GET_API_VERSION; no VM created
        print(f'kvm_api_version={api}')
        if api != 12:
            raise SystemExit('Unsupported KVM API version')
    finally:
        os.close(fd)
except OSError as exc:
    raise SystemExit(f'KVM probe failed: {exc}')
PY
    fi
else
    echo 'ERROR: /dev/kvm is absent' >&2
    status=1
fi
tracefs=''
for candidate in /sys/kernel/tracing /sys/kernel/debug/tracing; do
    if [[ -r $candidate/available_events ]]; then tracefs=$candidate; break; fi
done
if [[ -z $tracefs ]]; then
    echo 'ERROR: tracefs unavailable; check kernel tracing support, mount and permissions' >&2
    status=1
else
    echo "tracefs=$tracefs"
    for event in kvm:kvm_entry kvm:kvm_exit kvm:kvm_mmio kvm:kvm_pio sched:sched_switch sched:sched_wakeup; do
        if grep -qx "$event" "$tracefs/available_events"; then
            echo "AVAILABLE $event"
        else
            echo "MISSING   $event"
            case $event in kvm:kvm_entry|kvm:kvm_exit) status=1;; esac
        fi
    done
fi
if command -v trace-cmd >/dev/null; then
    version=$(trace-cmd --version 2>&1 || true)
    if [[ $version == *'trace-cmd version '* ]]; then
        printf '%s\n' "$version" | sed -n '/^trace-cmd version /p'
    else
        printf '%s\n' "$version" >&2
        status=1
    fi
else
    echo 'ERROR: trace-cmd not installed' >&2
    status=1
fi
exit "$status"
