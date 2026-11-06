/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "qemu/osdep.h"
#include "hw/virtio/virtio-pci.h"
#include "hw/qdev-properties.h"
#include "virtio-lab.h"
#include "lab-protocol.h"
#include "qemu/module.h"

typedef struct VirtIOLabPCI {
    VirtIOPCIProxy parent_obj;
    VirtIOLab vdev;
} VirtIOLabPCI;

#define TYPE_VIRTIO_LAB_PCI "virtio-lab-pci-base"
DECLARE_INSTANCE_CHECKER(VirtIOLabPCI, VIRTIO_LAB_PCI, TYPE_VIRTIO_LAB_PCI)

static void virtio_lab_pci_realize(VirtIOPCIProxy *proxy, Error **errp)
{
    VirtIOLabPCI *s = VIRTIO_LAB_PCI(proxy);
    qdev_realize(DEVICE(&s->vdev), BUS(&proxy->bus), errp);
}

static void virtio_lab_pci_instance_init(Object *obj)
{
    VirtIOLabPCI *s = VIRTIO_LAB_PCI(obj);
    virtio_instance_init_common(obj, &s->vdev, sizeof(s->vdev), TYPE_VIRTIO_LAB);
}

static void virtio_lab_pci_class_init(ObjectClass *klass, void *data)
{
    PCIDeviceClass *pc = PCI_DEVICE_CLASS(klass);
    VIRTIO_PCI_CLASS(klass)->realize = virtio_lab_pci_realize;
    pc->vendor_id = PCI_VENDOR_ID_REDHAT_QUMRANET;
    pc->device_id = 0x1040 + VIRTIO_LAB_DEVICE_ID;
    pc->revision = 1;
    pc->class_id = PCI_CLASS_OTHERS;
    set_bit(DEVICE_CATEGORY_MISC, DEVICE_CLASS(klass)->categories);
}

static const VirtioPCIDeviceTypeInfo virtio_lab_pci_info = {
    .base_name = TYPE_VIRTIO_LAB_PCI,
    .non_transitional_name = "virtio-lab-pci",
    .instance_size = sizeof(VirtIOLabPCI),
    .instance_init = virtio_lab_pci_instance_init,
    .class_init = virtio_lab_pci_class_init,
};

static void virtio_lab_pci_register_types(void)
{
    virtio_pci_types_register(&virtio_lab_pci_info);
}
type_init(virtio_lab_pci_register_types)
