#!/usr/bin/env bash
# Build a small initramfs using an existing Linux kernel + its standard modules.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
[[ $# == 3 ]] || { echo 'Usage: build_linux_guest.sh KERNEL MODULE_DIR NEW_OUTPUT'; exit 2; }
kernel=$(realpath "$1") modules=$(realpath "$2") output=$3
root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$(dirname "$output")"
mkdir "$output"
output=$(realpath "$output")
exec > >(tee "$output/build.log") 2>&1
mkdir -p "$output/root"/{bin,dev,proc,sys,data,modules,tmp}
cp "$kernel" "$output/kernel"
cp /usr/bin/busybox "$output/root/bin/busybox"
file /usr/bin/busybox | grep 'statically linked'
gcc -static -std=c11 -O2 -Wall -Wextra -Werror -pthread \
    "$root/kvm_exit_analyzer/workloads/linux_guest_workload.c" -o "$output/root/bin/lab-workload"
gcc -std=c11 -O2 -Wall -Wextra -Werror \
    "$root/kvm_exit_analyzer/workloads/perf_tid_map.c" -o "$output/perf_tid_map"
for module in virtio_blk e1000; do
    found=$(find "$modules/kernel" -name "$module.ko" -print -quit)
    [[ -n $found ]] || { echo "Missing existing standard module: $module"; exit 1; }
    cp "$found" "$output/root/modules/"
done
cat > "$output/root/init" <<'INIT'
#!/bin/busybox sh
export PATH=/bin
/bin/busybox --install -s /bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
exec </dev/ttyS0 >/dev/ttyS0 2>&1
stty -echo
insmod /modules/virtio_blk.ko
insmod /modules/e1000.ko
for n in 1 2 3 4 5; do
    disk=/dev/vda
    test -b "$disk" || disk=/dev/sda
    test -b "$disk" && break
    sleep 1
done
mount -t ext4 "$disk" /data || { echo LAB_BOOT_FAILED; poweroff -f; }
ifconfig lo up
ifconfig eth0 10.0.2.15 netmask 255.255.255.0 up
route add default gw 10.0.2.2
echo LAB_READY
while read -r mode seconds parameter; do
    if test "$mode" = poweroff; then sync; poweroff -f; fi
    if test "$mode" = inventory; then
        count=0
        for dev in /sys/bus/pci/devices/*; do
            if test "$(cat "$dev/vendor")" = 0x1af4 && test "$(cat "$dev/device")" = 0x107f; then
                echo "LAB_PCI $dev driver=$(readlink "$dev/driver")"
                count=$((count + 1))
            fi
        done
        echo "LAB_DEVICES $count"
        echo 'LAB_DONE 0'
        continue
    fi
    echo "LAB_START $mode"
    /bin/lab-workload "$mode" "$seconds" "$parameter"
    echo "LAB_DONE $?"
done
INIT
chmod +x "$output/root/init"
(cd "$output/root" && find . -print0 | cpio --null -o --format=newc) | gzip -1 > "$output/initramfs.gz"
truncate -s 192M "$output/disk.img"
mkfs.ext4 -q -F "$output/disk.img"
uname -a > "$output/host.txt"
printf 'kernel=%s\nmodules=%s\n' "$kernel" "$modules" >> "$output/host.txt"
echo "Guest assets built in $output"
