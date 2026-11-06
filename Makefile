PYTHON ?= python3
QEMU ?= build/qemu/qemu-9.2.0/build/qemu-system-x86_64
OUT ?= runs/manual
GUEST_ASSETS ?= build/guest-driver

.PHONY: test build-qemu qtest stress lifecycle packed soak guest-driver guest-driver-packed
test:
	bash run_offline_tests.sh

build-qemu:
	bash scripts/build_qemu.sh

qtest:
	$(PYTHON) qemu_virtio_lab/tests/qtest_smoke.py "$(QEMU)" --out "$(OUT)"

stress:
	$(PYTHON) qemu_virtio_lab/tests/qtest_smoke.py "$(QEMU)" --out "$(OUT)" --requests 65568 --resets 128

lifecycle:
	$(PYTHON) qemu_virtio_lab/tests/qmp_lifecycle.py "$(QEMU)" --out "$(OUT)"

packed:
	$(PYTHON) qemu_virtio_lab/tests/qtest_packed.py "$(QEMU)" --out "$(OUT)"

soak:
	$(PYTHON) qemu_virtio_lab/tests/qtest_soak.py "$(QEMU)" --out "$(OUT)" --seconds 600

guest-driver:
	$(PYTHON) qemu_virtio_lab/tests/guest_driver.py --qemu "$(QEMU)" --assets "$(GUEST_ASSETS)" --out "$(OUT)"

guest-driver-packed:
	$(PYTHON) qemu_virtio_lab/tests/guest_driver.py --qemu "$(QEMU)" --assets "$(GUEST_ASSETS)" --out "$(OUT)" --packed
