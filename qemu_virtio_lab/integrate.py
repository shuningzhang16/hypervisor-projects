#!/usr/bin/env python3
"""Install the experimental device in a separate QEMU 9.2.0 source checkout."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('qemu', type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    target = args.qemu.resolve()
    if (target / 'VERSION').read_text().strip() != (source / 'QEMU_VERSION').read_text().strip():
        parser.error('Use a QEMU v9.2.0 checkout; API changes require manual porting.')
    directory = target / 'hw/virtio'
    changes = {}
    for name in ('virtio-lab.c', 'virtio-lab.h', 'virtio-lab-pci.c', 'lab-protocol.c', 'lab-protocol.h'):
        path = directory / name
        content = (source / name).read_text(encoding='utf-8')
        if path.exists() and path.read_text(encoding='utf-8') != content:
            parser.error(f'Preserve/review existing edits in {path} before installing.')
        changes[path] = content
    meson = directory / 'meson.build'
    original = meson.read_text()
    anchor = "specific_ss.add_all(when: 'CONFIG_VIRTIO', if_true: specific_virtio_ss)"
    if 'CONFIG_VIRTIO_LAB' not in original:
        if original.count(anchor) != 1:
            parser.error('Expected QEMU Meson insertion point not found.')
        changes[meson] = original.replace(anchor, (source / 'meson.build.example').read_text() + '\n' + anchor)
    for name, marker, example in [('Kconfig', 'config VIRTIO_LAB', 'Kconfig.example'),
                                   ('trace-events', 'virtio_lab_notify(', 'trace-events.example')]:
        path = directory / name
        content = path.read_text()
        if marker not in content:
            changes[path] = content + '\n' + (source / example).read_text()
    # QEMU 9.2 looks up class/transport IDs in this table during device setup.
    path = directory / 'virtio-pci.c'
    content = path.read_text()
    anchor = 'static const VirtIOPCIIDInfo virtio_pci_id_info[] = {'
    if '.vdev_id = 63, /* virtio-lab: local experiment */' not in content:
        if content.count(anchor) != 1:
            parser.error('Expected QEMU VirtIO PCI ID table not found.')
        content = content.replace(anchor, anchor + '\n    {\n'
                                  '        .vdev_id = 63, /* virtio-lab: local experiment */\n'
                                  '        .trans_devid = 0,\n'
                                  '        .class_id = PCI_CLASS_OTHERS,\n    },')
        changes[path] = content
    path = directory / 'virtio.c'
    content = path.read_text()
    anchor = 'const char *virtio_device_names[] = {'
    if '[63] = "virtio-lab"' not in content:
        if content.count(anchor) != 1:
            parser.error('Expected QEMU VirtIO device name table not found.')
        changes[path] = content.replace(anchor, anchor + '\n    [63] = "virtio-lab", /* local experiment */')
    for path, content in changes.items():
        with path.open('w', encoding='utf-8', newline='\n') as handle:
            handle.write(content)
    print(f'Installed {len(changes)} files in {target}; compilation is a separate step.')


if __name__ == '__main__':
    main()
