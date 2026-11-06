#!/usr/bin/env python3
"""Exercise the actual PCI transport and virtqueue via QEMU qtest; no Guest OS/KVM."""
import argparse
import json
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path


def connect(path, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'QEMU exited with {process.returncode}; inspect stderr.log')
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(path))
            sock.settimeout(10)
            return sock
        except (FileNotFoundError, ConnectionRefusedError):
            sock.close()
            time.sleep(0.05)
    raise TimeoutError('QEMU socket did not become ready')


class QTest:
    def __init__(self, sock):
        self.stream = sock.makefile('rwb', buffering=0)

    def command(self, command):
        self.stream.write((command + '\n').encode())
        while True:
            line = self.stream.readline().decode().strip()
            if line.startswith('IRQ '):
                continue
            if not line.startswith('OK'):
                raise RuntimeError(f'{command}: {line}')
            return line[2:].strip()

    def read(self, address, size):
        return bytes.fromhex(self.command(f'read {address:#x} {size}').removeprefix('0x'))

    def write(self, address, data):
        self.command(f'write {address:#x} {len(data)} 0x{data.hex()}')

    def get(self, address, size):
        return int.from_bytes(self.read(address, size), 'little')

    def put(self, address, value, size):
        self.write(address, value.to_bytes(size, 'little'))

    def pci_get(self, offset, size=4):
        self.command(f'outl 0xcf8 {0x80002000 | (offset & ~3):#x}')
        op = {1: 'inb', 2: 'inw', 4: 'inl'}[size]
        return int(self.command(f'{op} {0xcfc + (offset & 3):#x}'), 0)

    def pci_put(self, offset, value, size=4):
        self.command(f'outl 0xcf8 {0x80002000 | (offset & ~3):#x}')
        op = {1: 'outb', 2: 'outw', 4: 'outl'}[size]
        self.command(f'{op} {0xcfc + (offset & 3):#x} {value:#x}')


def modern_caps(q):
    assert q.pci_get(0) == 0x107F1AF4, 'private modern PCI ID not found at slot 4'
    q.pci_put(0x20, 0xE0000000)  # BAR4: modern VirtIO capabilities
    q.pci_put(0x24, 0)
    q.pci_put(4, 6, 2)  # memory decoding and bus mastering
    caps = {}
    pos = q.pci_get(0x34, 1)
    for _ in range(48):
        if not pos:
            break
        if q.pci_get(pos, 1) == 9:
            kind = q.pci_get(pos + 3, 1)
            if kind in {1, 2, 3, 4}:
                assert q.pci_get(pos + 4, 1) == 4
                caps[kind] = 0xE0000000 + q.pci_get(pos + 8)
                if kind == 2:
                    multiplier = q.pci_get(pos + 16)
        pos = q.pci_get(pos + 1, 1)
    assert {1, 2, 3, 4} <= caps.keys()
    return caps, multiplier


def exercise(q, requests=0, resets=0):
    caps, multiplier = modern_caps(q)
    common = caps[1]
    assert q.get(caps[4], 4) == 1 and q.get(caps[4] + 4, 4) == 4096
    desc, avail, used = 0x100000, 0x101000, 0x102000
    request_address, response_address = 0x103000, 0x105000

    def setup(queue_size=8, feature_low=0):
        q.put(common + 20, 0, 1)
        assert q.get(common + 20, 1) == 0
        q.put(common + 20, 1, 1)  # ACKNOWLEDGE
        q.put(common + 20, 3, 1)  # ACKNOWLEDGE | DRIVER
        q.put(common, 1, 4)
        assert q.get(common + 4, 4) & 1  # VIRTIO_F_VERSION_1
        q.put(common + 8, 0, 4)
        q.put(common + 12, feature_low, 4)
        q.put(common + 8, 1, 4)
        q.put(common + 12, 1, 4)
        q.put(common + 20, 11, 1)  # FEATURES_OK
        assert q.get(common + 20, 1) & 8
        q.put(common + 22, 0, 2)
        assert q.get(common + 24, 2) == 64
        q.put(common + 24, queue_size, 2)
        q.put(common + 32, desc, 8)
        q.put(common + 40, avail, 8)
        q.put(common + 48, used, 8)
        q.write(desc, bytes(16 * queue_size))
        q.write(avail, bytes(6 + 2 * queue_size))
        q.write(used, bytes(6 + 8 * queue_size))
        q.put(common + 28, 1, 2)
        q.put(common + 20, 15, 1)  # DRIVER_OK

    def submit(request, capacity=4112, split=False, readable_only=False):
        setup()
        q.write(request_address, request)
        q.write(response_address, bytes([0xa5]) * (capacity + 1))
        if split:
            descriptors = [(request_address, 7, 1, 1), (request_address + 7, len(request) - 7, 1, 2),
                           (response_address, 5, 3, 3), (response_address + 5, capacity - 5, 2, 0)]
        elif readable_only:
            descriptors = [(request_address, len(request), 0, 0)]
        else:
            descriptors = [(request_address, len(request), 1, 1), (response_address, capacity, 2, 0)]
        for index, descriptor in enumerate(descriptors):
            q.write(desc + 16 * index, struct.pack('<QIHH', *descriptor))
        q.put(avail + 4, 0, 2)
        q.put(avail + 2, 1, 2)
        q.put(caps[2] + q.get(common + 30, 2) * multiplier, 0, 2)
        if readable_only or capacity < 16:
            assert q.get(common + 20, 1) & 64, 'invalid chain must require reset'
            assert q.get(used + 2, 2) == 0
            return None
        assert q.get(used + 2, 2) == 1, 'used ring was not advanced'
        head, length = struct.unpack('<II', q.read(used + 4, 8))
        assert head == 0 and length <= capacity
        assert q.get(response_address + capacity, 1) == 0xa5, 'response exceeded capacity'
        assert q.get(caps[3], 1) & 1, 'queue interrupt status not raised'
        return q.read(response_address, length)

    def request(payload=b'hello', opcode=1, declared=None):
        return struct.pack('<HHIQ', opcode, 0, len(payload) if declared is None else declared, 42) + payload

    result = submit(request(), split=True)
    assert result == struct.pack('<IIQ', 0, 5, 42) + b'hello'
    assert submit(request(b'')) == struct.pack('<IIQ', 0, 0, 42)
    payload = bytes(range(256)) * 16
    assert submit(request(payload)) == struct.pack('<IIQ', 0, 4096, 42) + payload
    assert submit(request(opcode=99)) == struct.pack('<IIQ', 2, 0, 42)
    assert submit(request(declared=99)) == struct.pack('<IIQ', 1, 0, 42)
    assert submit(request(), capacity=16) == struct.pack('<IIQ', 3, 0, 42)
    submit(request(), readable_only=True)
    submit(request(), capacity=8)
    assert submit(request(b'after-reset')).endswith(b'after-reset')
    for fault in ('loop', 'bad-next', 'write-before-read', 'unmapped'):
        setup()
        q.write(request_address, request())
        q.write(response_address, bytes([0xa5]) * 32)
        if fault == 'loop':
            chain = [(request_address, 21, 1, 0)]
        elif fault == 'bad-next':
            chain = [(request_address, 21, 1, 8)]
        elif fault == 'write-before-read':
            chain = [(response_address, 32, 3, 1), (request_address, 21, 0, 0)]
        else:
            chain = [(0xffffffffffff0000, 21, 1, 1), (response_address, 32, 2, 0)]
        q.write(desc, b''.join(struct.pack('<QIHH', *d) for d in chain))
        q.put(avail + 4, 0, 2)
        q.put(avail + 2, 1, 2)
        q.put(caps[2], 0, 2)
        if fault == 'unmapped':
            # QEMU 9.2 maps unassigned reads through a bounce buffer. The device
            # must return an empty BAD_REQUEST, never echo uninitialized data.
            assert q.get(used + 2, 2) == 1
            assert struct.unpack('<II', q.read(used + 4, 8)) == (0, 16)
            assert q.read(response_address, 8) == struct.pack('<II', 1, 0)
            assert q.read(response_address + 16, 16) == bytes([0xa5]) * 16
        else:
            assert q.get(common + 20, 1) & 64, f'{fault}: NEEDS_RESET not set'
            assert q.get(used + 2, 2) == 0, f'{fault}: invalid chain completed'
    # Negotiated indirect descriptors: one main-ring entry, two SG elements.
    for table_length in (32, 31):
        setup(feature_low=1 << 28)
        q.write(request_address, request())
        q.write(0x110000, struct.pack('<QIHHQIHH', request_address, 21, 1, 1,
                                     response_address, 32, 2, 0))
        q.write(desc, struct.pack('<QIHH', 0x110000, table_length, 4, 0))
        q.put(avail + 4, 0, 2)
        q.put(avail + 2, 1, 2)
        q.put(caps[2], 0, 2)
        if table_length == 32:
            assert q.get(used + 2, 2) == 1 and q.read(response_address + 16, 5) == b'hello'
        else:
            assert q.get(common + 20, 1) & 64 and q.get(used + 2, 2) == 0
    for index in range(resets):
        assert submit(request(struct.pack('<I', index))).endswith(struct.pack('<I', index))
    began = time.monotonic()
    if requests:
        setup(queue_size=64)
        descriptors = []
        for index in range(32):
            descriptors.extend([(request_address + index * 32, 24, 1, 2 * index + 1),
                                (response_address + index * 32, 32, 2, 0)])
        q.write(desc, b''.join(struct.pack('<QIHH', *d) for d in descriptors))
        q.write(avail + 4, struct.pack('<64H', *(list(range(0, 64, 2)) * 2)))
        completed = 0
        while completed < requests:
            count = min(32, requests - completed)
            payloads = [struct.pack('<Q', completed + i + 1) for i in range(count)]
            packets = [struct.pack('<HHIQ', 1, 0, 8, completed + i + 1) + p for i, p in enumerate(payloads)]
            q.write(request_address, b''.join(p + bytes(8) for p in packets))
            q.write(response_address, bytes([0xa5]) * (count * 32))
            suppressed = (completed // 32) % 2
            q.put(avail, suppressed, 2)  # VRING_AVAIL_F_NO_INTERRUPT
            q.put(avail + 2, (completed + count) & 0xffff, 2)
            q.put(caps[2], 0, 2)
            assert q.get(used + 2, 2) == ((completed + count) & 0xffff)
            used_ring = q.read(used + 4, 64 * 8)
            replies = q.read(response_address, count * 32)
            for i, payload in enumerate(payloads):
                assert struct.unpack_from('<II', used_ring, ((completed + i) % 64) * 8) == (2 * i, 24)
                expected = struct.pack('<IIQ', 0, 8, completed + i + 1) + payload + bytes([0xa5]) * 8
                assert replies[i * 32:(i + 1) * 32] == expected
            assert (q.get(caps[3], 1) & 1) == (not suppressed)
            completed += count
    # Drop an unnotified available request through reset, then recover normally.
    setup()
    q.write(response_address, bytes([0xa5]) * 32)
    q.write(desc, struct.pack('<QIHHQIHH', request_address, 24, 1, 1, response_address, 32, 2, 0))
    q.put(avail + 4, 0, 2)
    q.put(avail + 2, 1, 2)
    q.put(common + 20, 0, 1)
    q.put(caps[2], 0, 2)
    assert q.get(used + 2, 2) == 0 and q.read(response_address, 32) == bytes([0xa5]) * 32
    assert submit(request(b'recovered')).endswith(b'recovered')
    print('PASS: PCI/config, modern features, split SG echo, empty/max payload, errors, used ring/ISR, reset/recovery')
    print(f'PASS: malformed chains, indirect descriptors; {requests} batched requests; {resets} reset cycles')
    return {'requests': requests, 'reset_cycles': resets, 'index_wraps': requests // 65536,
            'qtest_wall_seconds': time.monotonic() - began, 'performance_scope': 'qtest IPC + emulation; not KVM performance'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('qemu', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--requests', type=int, default=0, help='batched stress requests; 65568 crosses the 16-bit ring index')
    parser.add_argument('--resets', type=int, default=0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='virtio-lab-') as tmp:
        socket_path = Path(tmp) / 'qtest.sock'
        command = [str(args.qemu.resolve()), '-machine', 'q35,accel=tcg', '-m', '64',
                   '-S', '-nodefaults', '-display', 'none', '-device', 'virtio-lab-pci,addr=4.0',
                   '-qtest', f'unix:{socket_path},server=on,wait=off',
                   '-qtest-log', '/dev/null',
                   '-trace', 'enable=virtio_lab_*', '-D', str(args.out / 'device-trace.log')]
        (args.out / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        with (args.out / 'stderr.log').open('w') as err:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
            sock = None
            try:
                sock = connect(socket_path, process)
                result = exercise(QTest(sock), requests=args.requests, resets=args.resets)
                (args.out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
                (args.out / 'result.txt').write_text('PASS: qtest transport checks; no Guest OS or KVM benchmark\n')
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if sock is not None:
                    sock.close()


if __name__ == '__main__':
    main()
