#!/usr/bin/env bash
# Download/extract only. No package installation, host boot change or module load.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
dest=${1:?Usage: prepare_driver_kernel.sh NEW_DIRECTORY}
mkdir "$dest"
dest=$(realpath "$dest")
exec > >(tee "$dest/prepare.log") 2>&1
mkdir "$dest/packages" "$dest/root"
cd "$dest/packages"
apt-get download linux-image-5.15.0-194-generic linux-modules-5.15.0-194-generic \
    linux-headers-5.15.0-194 linux-headers-5.15.0-194-generic
for package in *.deb; do
    dpkg-deb -f "$package" Package Version
    dpkg-deb -x "$package" "$dest/root"
done
ls -l "$dest/root/boot" "$dest/root/usr/src"
head -n 12 "$dest/root/usr/src/linux-headers-5.15.0-194-generic/Makefile"
