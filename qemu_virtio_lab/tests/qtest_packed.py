#!/usr/bin/env python3
"""Actual QEMU packed-ring transport checks via qtest; no custom Guest driver."""
import argparse
import json
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from qtest_smoke import QTest, connect, modern_caps


def exercise(q, requests):
    caps, multiplier = modern_caps(q)
    common = caps[1]
    ring, driver_event, device_event = 0x100000, 0x101000, 0x102000
    request, response = 0x103000, 0x105000
    index, wrap, wraps = 0, 1, 0

    def setup():
        nonlocal index, wrap
        q.put(common + 20, 0, 1)
        assert q.get(common + 20, 1) == 0
        q.put(common + 20, 3, 1)
        q.put(common, 1, 4)
        assert q.get(common + 4, 4) & 5 == 5  # VERSION_1 + RING_PACKED
        q.put(common + 8, 0, 4); q.put(common + 12, 0, 4)
        q.put(common + 8, 1, 4); q.put(common + 12, 5, 4)
        q.put(common + 20, 11, 1)
        assert q.get(common + 20, 1) & 8
        q.put(common + 22, 0, 2)
        q.put(common + 24, 8, 2)
        q.put(common + 32, ring, 8)
        q.put(common + 40, driver_event, 8)
        q.put(common + 48, device_event, 8)
        q.write(ring, bytes(8 * 16))
        q.write(driver_event, bytes(4)); q.write(device_event, bytes(4))
        q.put(common + 28, 1, 2); q.put(common + 20, 15, 1)
        index, wrap = 0, 1
        q.get(caps[3], 1)  # clear pending ISR after reset

    def submit(number, split=False, suppress=False, opcode=1):
        nonlocal index, wrap, wraps
        payload = struct.pack('<Q', number)
        req = struct.pack('<HHIQ', opcode, 0, 8, number) + payload
        q.write(request, req); q.write(response, bytes([0xa5]) * 32)
        q.put(driver_event + 2, int(suppress), 2)  # ENABLE=0 / DISABLE=1
        head, head_wrap = index, wrap
        parts = [(request, 24, 1), (response, 31, 2)]
        if split:
            parts = [(request, 7, 1), (request + 7, 17, 1), (response, 31, 2)]
        for address, length, flags in parts:
            bits = (wrap << 7) | ((1 - wrap) << 15)
            q.write(ring + index * 16, struct.pack('<QIHH', address, length, number & 0xffff, flags | bits))
            index += 1
            if index == 8:
                index = 0; wrap ^= 1; wraps += 1
        q.put(caps[2] + q.get(common + 30, 2) * multiplier, 0, 2)
        _, length, ident, flags = struct.unpack('<QIHH', q.read(ring + head * 16, 16))
        assert (flags >> 7) & 1 == head_wrap and (flags >> 15) & 1 == head_wrap
        expected = struct.pack('<IIQ', 0 if opcode == 1 else 2, 8 if opcode == 1 else 0, number)
        if opcode == 1:
            expected += payload
        assert ident == number & 0xffff and length == len(expected)
        assert q.read(response, len(expected)) == expected
        assert q.read(response + len(expected), 32 - len(expected)) == bytes([0xa5]) * (32 - len(expected))
        assert bool(q.get(caps[3], 1) & 1) == (not suppress)

    setup()
    began = time.monotonic()
    for number in range(requests):
        submit(number, split=number % 9 == 0, suppress=number % 2 == 0,
               opcode=99 if number % 17 == 0 else 1)
    for number in range(32):
        setup(); submit(number)
    # Invalid readable-only chain must set NEEDS_RESET without writing a response.
    setup()
    q.write(response, bytes([0xa5]) * 32)
    q.write(ring, struct.pack('<QIHH', request, 24, 1, 0x80))
    q.put(caps[2], 0, 2)
    assert q.get(common + 20, 1) & 64
    assert q.read(response, 32) == bytes([0xa5]) * 32
    setup(); submit(12345, split=True)
    return {'requests': requests, 'wrap_transitions': wraps, 'reset_cycles': 32,
            'wall_seconds': time.monotonic() - began, 'result': 'PASS',
            'checks': ['packed features', 'SG across wrap', 'content/used ID/length',
                       'notification suppression', 'unsupported opcode', 'reset', 'fatal chain recovery'],
            'scope': 'TCG qtest transport functionality; not KVM performance'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('qemu', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--requests', type=int, default=4096)
    args = parser.parse_args()
    if not 1 <= args.requests <= 1000000:
        parser.error('requests 1..1000000')
    args.out.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='lab-packed-') as tmp:
        socket_path = Path(tmp) / 'qtest'
        command = [str(args.qemu.resolve()), '-machine', 'q35,accel=tcg', '-m', '64', '-S',
                   '-nodefaults', '-display', 'none', '-device', 'virtio-lab-pci,addr=4.0,packed=on',
                   '-qtest', f'unix:{socket_path},server=on,wait=off', '-qtest-log', '/dev/null']
        (args.out / 'command.json').write_text(json.dumps(command, indent=2))
        with (args.out / 'stderr.log').open('w') as err:
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
            sock = None
            try:
                sock = connect(socket_path, proc)
                result = exercise(QTest(sock), args.requests)
                (args.out / 'summary.json').write_text(json.dumps(result, indent=2))
                print(json.dumps(result))
            finally:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
                if sock: sock.close()


if __name__ == '__main__': main()
