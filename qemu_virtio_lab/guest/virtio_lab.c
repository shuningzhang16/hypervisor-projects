// SPDX-License-Identifier: GPL-2.0-or-later
/* Experimental Guest-only driver for the private, unassigned VirtIO ID 63. */
#include <linux/module.h>
#include <linux/virtio.h>
#include <linux/virtio_config.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/compat.h>
#include <linux/completion.h>
#include <linux/kref.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/ktime.h>
#include <asm/unaligned.h>
#include "lab_uapi.h"

#define LAB_HEADER 16
#define LAB_MESSAGE (LAB_HEADER + LAB_MAX_PAYLOAD)
static unsigned int timeout_ms = 1000;
module_param(timeout_ms, uint, 0444);
MODULE_PARM_DESC(timeout_ms, "Bounded request timeout, 50..5000 ms");
static bool test_skip_kick;
module_param(test_skip_kick, bool, 0444);
MODULE_PARM_DESC(test_skip_kick, "TEST ONLY: enqueue without notify to exercise timeout cleanup");

struct lab_request {
    u8 out[LAB_MESSAGE];
    u8 in[LAB_MESSAGE];
    unsigned int used;
    u64 callback_ns;
};
struct lab_device {
    struct virtio_device *vdev;
    struct virtqueue *vq;
    struct miscdevice misc;
    char name[64];
    struct mutex operation;
    spinlock_t queue_lock;
    struct completion completion;
    struct kref references;
    struct lab_info info;
    u64 callbacks;
    bool dead;
    bool failed;
};

static void lab_release_device(struct kref *ref)
{
    struct lab_device *dev = container_of(ref, struct lab_device, references);
    kfree(dev);
}

static void lab_complete(struct virtqueue *vq)
{
    struct lab_device *dev = vq->vdev->priv;
    struct lab_request *request;
    unsigned int used;
    unsigned long flags;

    spin_lock_irqsave(&dev->queue_lock, flags);
    while ((request = virtqueue_get_buf(vq, &used))) {
        request->used = used;
        request->callback_ns = ktime_get_ns();
        dev->callbacks++;
        complete(&dev->completion);
    }
    spin_unlock_irqrestore(&dev->queue_lock, flags);
}

/* operation mutex held. Caller keeps every request alive until this returns. */
static void lab_stop(struct lab_device *dev)
{
    unsigned long flags;
    if (!dev->vq)
        return;
    dev->vdev->config->reset(dev->vdev); /* Stop device DMA before reclaiming buffers. */
    spin_lock_irqsave(&dev->queue_lock, flags);
    while (virtqueue_detach_unused_buf(dev->vq))
        ; /* Single in-flight request is owned/freed by the ioctl caller. */
    spin_unlock_irqrestore(&dev->queue_lock, flags);
    /* PCI del_vqs frees/synchronizes IRQ handlers before request/device memory is freed. */
    dev->vdev->config->del_vqs(dev->vdev);
    dev->vq = NULL;
}

static int lab_open(struct inode *inode, struct file *file)
{
    struct miscdevice *misc = file->private_data;
    struct lab_device *dev = container_of(misc, struct lab_device, misc);
    /* misc core serializes open with deregistration; remove retains its initial ref. */
    kref_get(&dev->references);
    file->private_data = dev;
    return nonseekable_open(inode, file);
}

static int lab_close(struct inode *inode, struct file *file)
{
    struct lab_device *dev = file->private_data;
    kref_put(&dev->references, lab_release_device);
    return 0;
}

static long lab_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    struct lab_device *dev = file->private_data;
    void __user *user = (void __user *)arg;
    struct lab_transfer *transfer = NULL;
    struct lab_request *request = NULL;
    struct scatterlist out[2], in;
    struct scatterlist *lists[] = {out, &in};
    unsigned long flags;
    u64 started;
    int rc = 0;

    if (cmd != LAB_IOC_INFO && cmd != LAB_IOC_TRANSFER)
        return -ENOTTY;
    if (mutex_lock_interruptible(&dev->operation))
        return -ERESTARTSYS;
    if (dev->dead) { rc = -ENODEV; goto done; }
    if (dev->failed) { rc = -EIO; goto done; }
    if (cmd == LAB_IOC_INFO) {
        rc = copy_to_user(user, &dev->info, sizeof(dev->info)) ? -EFAULT : 0;
        goto done;
    }
    transfer = memdup_user(user, sizeof(*transfer));
    if (IS_ERR(transfer)) { rc = PTR_ERR(transfer); transfer = NULL; goto done; }
    if (transfer->length > LAB_MAX_PAYLOAD) { rc = -EMSGSIZE; goto done; }
    if (transfer->response_capacity < LAB_HEADER || transfer->response_capacity > LAB_MESSAGE) {
        rc = -EINVAL; goto done;
    }
    request = kzalloc(sizeof(*request), GFP_KERNEL);
    if (!request) { rc = -ENOMEM; goto done; }
    put_unaligned_le16(transfer->opcode, request->out);
    put_unaligned_le16(transfer->flags, request->out + 2);
    put_unaligned_le32(transfer->length, request->out + 4);
    put_unaligned_le64(transfer->request_id, request->out + 8);
    memcpy(request->out + LAB_HEADER, transfer->input, transfer->length);
    memset(request->in, 0xa5, sizeof(request->in));
    sg_init_table(out, transfer->length ? 2 : 1);
    sg_set_buf(&out[0], request->out, LAB_HEADER);
    if (transfer->length)
        sg_set_buf(&out[1], request->out + LAB_HEADER, transfer->length);
    sg_init_one(&in, request->in, transfer->response_capacity);
    reinit_completion(&dev->completion);
    started = ktime_get_ns();
    spin_lock_irqsave(&dev->queue_lock, flags);
    rc = virtqueue_add_sgs(dev->vq, lists, 1, 1, request, GFP_ATOMIC);
    if (!rc && !test_skip_kick)
        virtqueue_kick(dev->vq);
    spin_unlock_irqrestore(&dev->queue_lock, flags);
    if (rc)
        goto done;
    if (!wait_for_completion_timeout(&dev->completion, msecs_to_jiffies(timeout_ms))) {
        dev->failed = true;
        lab_stop(dev);
        dev_warn(&dev->vdev->dev, "request timed out; queue reclaimed; rebind required\n");
        rc = -ETIMEDOUT;
        goto done;
    }
    transfer->submit_to_return_ns = ktime_get_ns() - started;
    transfer->submit_to_callback_ns = request->callback_ns - started;
    /* Synchronize with the callback before its token is released. */
    spin_lock_irqsave(&dev->queue_lock, flags);
    transfer->completed_callbacks = dev->callbacks;
    spin_unlock_irqrestore(&dev->queue_lock, flags);
    transfer->status = get_unaligned_le32(request->in);
    transfer->response_length = get_unaligned_le32(request->in + 4);
    transfer->used_length = request->used;
    if (request->used < LAB_HEADER || request->used > transfer->response_capacity ||
        transfer->response_length > LAB_MAX_PAYLOAD ||
        request->used != LAB_HEADER + transfer->response_length ||
        get_unaligned_le64(request->in + 8) != transfer->request_id || transfer->status > 3) {
        dev->failed = true; lab_stop(dev); rc = -EPROTO; goto done;
    }
    memset(transfer->output, 0, sizeof(transfer->output));
    memcpy(transfer->output, request->in + LAB_HEADER, transfer->response_length);
    rc = copy_to_user(user, transfer, sizeof(*transfer)) ? -EFAULT : 0;
done:
    kfree(request);
    kfree(transfer);
    mutex_unlock(&dev->operation);
    return rc;
}

static const struct file_operations lab_fops = {
    .owner = THIS_MODULE, .open = lab_open, .release = lab_close,
    .unlocked_ioctl = lab_ioctl,
#ifdef CONFIG_COMPAT
    .compat_ioctl = compat_ptr_ioctl,
#endif
    .llseek = no_llseek,
};

static int lab_probe(struct virtio_device *vdev)
{
    struct lab_device *dev;
    __le32 config[2];
    int rc;
    if (timeout_ms < 50 || timeout_ms > 5000)
        return -EINVAL;
    vdev->config->get(vdev, 0, config, sizeof(config));
    if (le32_to_cpu(config[0]) != 1 || le32_to_cpu(config[1]) != LAB_MAX_PAYLOAD)
        return -ENODEV;
    dev = kzalloc(sizeof(*dev), GFP_KERNEL);
    if (!dev) return -ENOMEM;
    dev->vdev = vdev;
    mutex_init(&dev->operation);
    spin_lock_init(&dev->queue_lock);
    init_completion(&dev->completion);
    kref_init(&dev->references);
    vdev->priv = dev;
    dev->vq = virtio_find_single_vq(vdev, lab_complete, "requests");
    if (IS_ERR(dev->vq)) { rc = PTR_ERR(dev->vq); goto free_device; }
    dev->info.version = 1;
    dev->info.max_payload = LAB_MAX_PAYLOAD;
    dev->info.queue_size = virtqueue_get_vring_size(dev->vq);
    dev->info.packed = virtio_has_feature(vdev, VIRTIO_F_RING_PACKED);
    snprintf(dev->name, sizeof(dev->name), "virtio-lab-%s", dev_name(&vdev->dev));
    dev->misc.minor = MISC_DYNAMIC_MINOR;
    dev->misc.name = dev->name;
    dev->misc.fops = &lab_fops;
    dev->misc.parent = &vdev->dev;
    dev->misc.mode = 0600;
    virtio_device_ready(vdev);
    rc = misc_register(&dev->misc);
    if (rc) { lab_stop(dev); goto free_device; }
    dev_info(&vdev->dev, "ready: private ID 63, packed=%u queue=%u\n", dev->info.packed, dev->info.queue_size);
    return 0;
free_device:
    vdev->priv = NULL;
    kref_put(&dev->references, lab_release_device);
    return rc;
}

static void lab_remove(struct virtio_device *vdev)
{
    struct lab_device *dev = vdev->priv;
    /* Do not hold operation while deregistering: misc core serializes new opens. */
    misc_deregister(&dev->misc);
    mutex_lock(&dev->operation);
    dev->dead = true;
    lab_stop(dev);
    mutex_unlock(&dev->operation);
    vdev->priv = NULL;
    dev_info(&vdev->dev, "removed: queue stopped; open-file references retained safely\n");
    kref_put(&dev->references, lab_release_device);
}

static const struct virtio_device_id lab_ids[] = {
    { 63, VIRTIO_DEV_ANY_ID }, { 0 },
};
static struct virtio_driver lab_driver = {
    .driver.name = "virtio_lab", .driver.owner = THIS_MODULE,
    .id_table = lab_ids, .probe = lab_probe, .remove = lab_remove,
};
module_virtio_driver(lab_driver);
MODULE_DEVICE_TABLE(virtio, lab_ids);
MODULE_DESCRIPTION("Experimental virtio-lab Guest echo driver (private device ID 63)");
MODULE_LICENSE("GPL");
