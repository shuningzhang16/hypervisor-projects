#!/usr/bin/env python3
"""Small QMP/serial harness for a real Linux guest. Uses existing Linux drivers."""
import json
import re
import select
import socket
import subprocess
import tempfile
import time
from pathlib import Path


def connect(path, process):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('QEMU exited; inspect qemu.stderr')
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(path))
            sock.settimeout(20)
            return sock
        except (FileNotFoundError, ConnectionRefusedError):
            sock.close()
            time.sleep(.05)
    raise TimeoutError('QEMU socket startup')


class LinuxGuest:
    def __init__(self, qemu, assets, output, *, vcpus=2, memory=256,
                 disk='virtio', nic='virtio', map_tids=True, extra_args=(), accelerator='kvm'):
        self.output = Path(output)
        self.output.mkdir(parents=True)
        self.assets = Path(assets)
        self.tmp = tempfile.TemporaryDirectory(prefix='linux-lab-')
        tmp = Path(self.tmp.name)
        self.logs = []
        self.sockets = []
        self.events = []
        self.serial_buffer = b''
        self.mapper = None
        self.proc = None
        # A fresh disposable copy per VM, no shared writable backing disk.
        scratch = tmp / 'disk.img'
        subprocess.run(['cp', '--reflink=auto', str(self.assets / 'disk.img'), str(scratch)], check=True)
        if accelerator not in {'kvm', 'tcg'}:
            raise ValueError('accelerator must be kvm or tcg')
        command = [str(qemu), '-machine', f'q35,accel={accelerator}', '-cpu', 'host' if accelerator == 'kvm' else 'max', '-S',
                   '-m', str(memory), '-smp', str(vcpus), '-nodefaults', '-display', 'none',
                   '-kernel', str(self.assets / 'kernel'), '-initrd', str(self.assets / 'initramfs.gz'),
                   '-append', 'console=ttyS0 rdinit=/init panic=-1',
                   '-serial', f'unix:{tmp}/serial,server=on,wait=off',
                   '-qmp', f'unix:{tmp}/qmp,server=on,wait=off',
                   '-drive', f'file={scratch},if=none,id=disk,format=raw,cache=none,aio=threads',
                   '-device', 'virtio-blk-pci,drive=disk' if disk == 'virtio' else 'ide-hd,drive=disk,bus=ide.0',
                   '-netdev', 'user,id=net', '-device',
                   ('virtio-net-pci' if nic == 'virtio' else 'e1000') + ',netdev=net',
                   '-device', 'pcie-root-port,id=labport,chassis=1,slot=1']
        command.extend(map(str, extra_args))
        (self.output / 'command.json').write_text(json.dumps(command, indent=2))
        try:
            err = self.open_log('qemu.stderr')
            self.proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
            monitor = connect(tmp / 'qmp', self.proc)
            self.sockets.append(monitor)
            self.qmp_stream = monitor.makefile('rwb', buffering=0)
            self.logs.append(self.qmp_stream)
            self.qmp_log = self.open_log('qmp.jsonl')
            self.qmp_log.write(self.qmp_stream.readline())
            self.qmp('qmp_capabilities')
            self.serial = connect(tmp / 'serial', self.proc)
            self.sockets.append(self.serial)
            self.serial_log = self.open_log('serial.log')
            cpus = self.qmp('query-cpus-fast')
            (self.output / 'cpus.json').write_text(json.dumps(cpus, indent=2))
            if map_tids:
                self.start_mapper([cpu['thread-id'] for cpu in cpus])
            self.qmp('cont')
            if self.mapper:
                rest, _ = self.mapper.communicate(timeout=20)
                self.mapper_log.write(rest.encode()); self.mapper_log.flush()
                if self.mapper.returncode:
                    raise RuntimeError('perf TID mapping failed; inspect mapper logs')
                self.tid_map = json.loads(rest)['mapping']
                (self.output / 'tid-map.json').write_text(json.dumps(self.tid_map, indent=2))
            self.read_until('LAB_READY', timeout=90)
        except BaseException:
            self.close()
            raise

    def open_log(self, name):
        log = (self.output / name).open('wb')
        self.logs.append(log)
        return log

    def qmp(self, execute, arguments=None):
        request = {'execute': execute}
        if arguments is not None:
            request['arguments'] = arguments
        line = (json.dumps(request) + '\n').encode()
        self.qmp_log.write(line); self.qmp_log.flush()
        self.qmp_stream.write(line)
        while True:
            line = self.qmp_stream.readline()
            if not line:
                raise RuntimeError('QMP connection closed')
            self.qmp_log.write(line); self.qmp_log.flush()
            reply = json.loads(line)
            if 'event' in reply:
                self.events.append(reply)
            elif 'error' in reply:
                raise RuntimeError(f'QMP {execute}: {reply}')
            else:
                return reply['return']

    def start_mapper(self, tids):
        trace = Path('/sys/kernel/tracing/events/raw_syscalls/sys_enter')
        event_id = trace.joinpath('id').read_text().strip()
        offset = re.search(r'field:int common_pid;\s*offset:(\d+);', trace.joinpath('format').read_text())
        if not offset:
            raise RuntimeError('common_pid format unavailable')
        command = [str(self.assets / 'perf_tid_map'), event_id, offset[1], *map(str, tids)]
        (self.output / 'mapper-command.json').write_text(json.dumps(command))
        self.mapper_log = self.open_log('mapper.jsonl')
        self.mapper = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=self.open_log('mapper.stderr'), text=True)
        ready = self.mapper.stdout.readline()
        self.mapper_log.write(ready.encode()); self.mapper_log.flush()
        if not ready or not json.loads(ready).get('ready'):
            raise RuntimeError('perf mapper not ready; inspect mapper.stderr')

    def read_until(self, marker, timeout):
        deadline = time.monotonic() + timeout
        lines = []
        while time.monotonic() < deadline:
            while b'\n' in self.serial_buffer:
                raw, self.serial_buffer = self.serial_buffer.split(b'\n', 1)
                line = raw.decode(errors='replace').strip()
                lines.append(line)
                if line.startswith(marker):
                    return lines
            readable, _, _ = select.select([self.serial], [], [], min(1, max(0, deadline - time.monotonic())))
            if readable:
                data = self.serial.recv(65536)
                if not data:
                    raise RuntimeError('Guest serial closed')
                self.serial_log.write(data); self.serial_log.flush()
                self.serial_buffer += data
        raise TimeoutError(f'Guest did not send {marker}; inspect serial.log')

    def workload(self, mode, seconds, parameter):
        self.serial.sendall(f'{mode} {seconds} {parameter}\n'.encode())
        lines = self.read_until('LAB_DONE', timeout=seconds + 30)
        if lines[-1] != 'LAB_DONE 0':
            raise RuntimeError(f'Guest workload failed: {lines}')
        return next(json.loads(line) for line in lines if line.startswith('{"mode"'))

    def close(self):
        if self.mapper and self.mapper.poll() is None:
            self.mapper.terminate(); self.mapper.wait(timeout=10)
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait()
        for log in self.logs:
            log.close()
        for sock in self.sockets:
            sock.close()
        self.tmp.cleanup()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with LinuxGuest(args.qemu, args.assets, args.out) as guest:
        result = guest.workload('cpu', 2, 2)
        (args.out / 'smoke.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
