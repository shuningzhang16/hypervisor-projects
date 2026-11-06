/* SPDX-License-Identifier: GPL-2.0-or-later
 * Target: QEMU v9.2.0. See VALIDATION.md for actual validation scope.
 */
#include "qemu/osdep.h"
#include "virtio-lab.h"
#include "lab-protocol.h"
#include "qemu/iov.h"
#include "qemu/module.h"
#include "qemu/timer.h"
#include "migration/vmstate.h"
#include "trace.h"

#define LAB_QUEUE_SIZE 64

static void virtio_lab_process(void *opaque)
{
    VirtIOLab *s = opaque;
    VirtIODevice *vdev = VIRTIO_DEVICE(s);
    unsigned budget = LAB_QUEUE_SIZE;
    bool completed = false;

    if (!(vdev->status & VIRTIO_CONFIG_S_DRIVER_OK) || vdev->broken) {
        return;
    }
    while (budget--) {
        VirtQueueElement *elem = virtqueue_pop(s->vq, sizeof(*elem));
        uint8_t request[LAB_MAX_MESSAGE], response[LAB_MAX_MESSAGE];
        size_t out_len, in_len, used;
        if (!elem) {
            break;
        }
        out_len = iov_size(elem->out_sg, elem->out_num);
        in_len = iov_size(elem->in_sg, elem->in_num);
        if (!elem->out_num || !elem->in_num ||
            out_len < LAB_HEADER_SIZE || out_len > sizeof(request) ||
            in_len < LAB_HEADER_SIZE) {
            /* Cannot safely return a structured response: consume nothing and
             * require a guest reset. Never read/write outside mapped buffers. */
            virtqueue_detach_element(s->vq, elem, 0);
            g_free(elem);
            virtio_error(vdev, "virtio-lab: invalid descriptor directions/lengths");
            return;
        }
        if (iov_to_buf(elem->out_sg, elem->out_num, 0, request, out_len) != out_len) {
            virtqueue_detach_element(s->vq, elem, 0);
            g_free(elem);
            virtio_error(vdev, "virtio-lab: short request copy");
            return;
        }
        used = lab_respond(request, out_len, response, MIN(in_len, sizeof(response)));
        if (!used || iov_from_buf(elem->in_sg, elem->in_num, 0, response, used) != used) {
            virtqueue_detach_element(s->vq, elem, 0);
            g_free(elem);
            virtio_error(vdev, "virtio-lab: short response copy");
            return;
        }
        virtqueue_push(s->vq, elem, used);
        trace_virtio_lab_complete(s, ldq_le_p(response + 8), ldl_le_p(response),
                                  used, qemu_clock_get_ns(QEMU_CLOCK_REALTIME) - s->kick_ns);
        g_free(elem);
        completed = true;
    }
    if (completed) {
        virtio_notify(vdev, s->vq);
    }
    if (!vdev->broken && !virtio_queue_empty(s->vq)) {
        /* Bounded work per callback; continue even if the guest refills without
         * another kick. No descriptor is retained between callbacks. */
        qemu_bh_schedule(s->bh);
    }
}

static void virtio_lab_handle_output(VirtIODevice *vdev, VirtQueue *vq)
{
    VirtIOLab *s = VIRTIO_LAB(vdev);
    s->kick_ns = qemu_clock_get_ns(QEMU_CLOCK_REALTIME);
    trace_virtio_lab_notify(s, s->kick_ns);
    virtio_lab_process(s);
}

static uint64_t virtio_lab_get_features(VirtIODevice *vdev, uint64_t features, Error **errp)
{
    /* No device-specific feature bits in protocol v1; transport bits preserved. */
    return features;
}

static void virtio_lab_get_config(VirtIODevice *vdev, uint8_t *config)
{
    stl_le_p(config, LAB_VERSION);
    stl_le_p(config + 4, LAB_MAX_PAYLOAD);
}

static void virtio_lab_reset(VirtIODevice *vdev)
{
    VirtIOLab *s = VIRTIO_LAB(vdev);
    qemu_bh_cancel(s->bh);
    s->kick_ns = 0;
    /* Core resets rings. Synchronous requests leave no retained elements. */
    trace_virtio_lab_reset(s);
}

static void virtio_lab_realize(DeviceState *dev, Error **errp)
{
    VirtIOLab *s = VIRTIO_LAB(dev);
    VirtIODevice *vdev = VIRTIO_DEVICE(dev);
    virtio_init(vdev, VIRTIO_LAB_DEVICE_ID, 8);
    s->vq = virtio_add_queue(vdev, LAB_QUEUE_SIZE, virtio_lab_handle_output);
    s->bh = qemu_bh_new(virtio_lab_process, s);
}

static void virtio_lab_unrealize(DeviceState *dev)
{
    VirtIOLab *s = VIRTIO_LAB(dev);
    qemu_bh_delete(s->bh);
    virtio_del_queue(VIRTIO_DEVICE(dev), 0);
    virtio_cleanup(VIRTIO_DEVICE(dev));
}

static const VMStateDescription vmstate_virtio_lab = {
    .name = "virtio-lab",
    .unmigratable = true,
};

static void virtio_lab_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    VirtioDeviceClass *vdc = VIRTIO_DEVICE_CLASS(klass);
    dc->desc = "Private experimental VirtIO echo device";
    dc->vmsd = &vmstate_virtio_lab;
    set_bit(DEVICE_CATEGORY_MISC, dc->categories);
    vdc->realize = virtio_lab_realize;
    vdc->unrealize = virtio_lab_unrealize;
    vdc->get_features = virtio_lab_get_features;
    vdc->get_config = virtio_lab_get_config;
    vdc->reset = virtio_lab_reset;
}

static const TypeInfo virtio_lab_info = {
    .name = TYPE_VIRTIO_LAB,
    .parent = TYPE_VIRTIO_DEVICE,
    .instance_size = sizeof(VirtIOLab),
    .class_init = virtio_lab_class_init,
};

static void virtio_lab_register_types(void)
{
    type_register_static(&virtio_lab_info);
}
type_init(virtio_lab_register_types)
