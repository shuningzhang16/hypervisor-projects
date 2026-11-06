#!/usr/bin/env bash
# All writes are under NEW_OUTPUT. Never loads a module on the host.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
[[ $# == 2 ]] || { echo 'Usage: build_guest_driver.sh EXTRACTED_KERNEL_ROOT NEW_OUTPUT'; exit 2; }
packages=$(realpath "$1")
project=$(cd "$(dirname "$0")/.." && pwd)
mkdir "$2"
output=$(realpath "$2")
exec > >(tee "$output/build.log") 2>&1
cp -a "$project/qemu_virtio_lab/guest" "$output/module"
make -C "$packages/usr/src/linux-headers-5.15.0-194-generic" M="$output/module" W=1 modules
gcc -static -std=c11 -O2 -Wall -Wextra -Werror -pthread \
    "$project/qemu_virtio_lab/guest/lab_client.c" -o "$output/lab-client"
mkdir -p "$output/root"/{bin,dev,proc,sys,tmp,modules}
cp /usr/bin/busybox "$output/root/bin/"
cp "$output/lab-client" "$output/root/bin/"
cp "$output/module/virtio_lab.ko" "$output/root/modules/"
cp "$packages/boot/vmlinuz-5.15.0-194-generic" "$output/kernel"
# Use existing standard VirtIO PCI transport dependencies in their loading order.
for name in virtio virtio_ring virtio_pci_modern_dev virtio_pci_legacy_dev virtio_pci; do
    module=$(find "$packages/lib/modules" -name "$name.ko" -print -quit)
    if [[ -n $module ]]; then cp "$module" "$output/root/modules/"; fi
done
cp "$project/qemu_virtio_lab/guest/init" "$output/root/init"
chmod +x "$output/root/init"
(cd "$output/root" && find . -print0 | cpio --null -o --format=newc) | gzip -1 > "$output/initramfs.gz"
# Harness compatibility; guest does not mount or access this disposable image.
truncate -s 1M "$output/disk.img"
printf 'Guest kernel: 5.15.0-194-generic\nUbuntu package version: 5.15.0-194.204\n' > "$output/versions.txt"
uname -a >> "$output/versions.txt"
echo "Built Guest driver and initramfs in $output"
