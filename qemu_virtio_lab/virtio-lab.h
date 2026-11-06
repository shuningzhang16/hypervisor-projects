/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef HW_VIRTIO_LAB_H
#define HW_VIRTIO_LAB_H
#include "hw/virtio/virtio.h"
#include "qemu/main-loop.h"
#include "qom/object.h"

#define TYPE_VIRTIO_LAB "virtio-lab-device"
OBJECT_DECLARE_SIMPLE_TYPE(VirtIOLab, VIRTIO_LAB)

struct VirtIOLab {
    VirtIODevice parent_obj;
    VirtQueue *vq;
    QEMUBH *bh;
    int64_t kick_ns;
};
#endif
