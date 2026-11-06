/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VIRTIO_LAB_UAPI_H
#define VIRTIO_LAB_UAPI_H
#include <linux/ioctl.h>
#include <linux/types.h>

#define LAB_MAX_PAYLOAD 4096
struct lab_info {
    __u32 version;
    __u32 max_payload;
    __u32 queue_size;
    __u32 packed;
};
struct lab_transfer {
    __u16 opcode;
    __u16 flags;
    __u32 length;
    __aligned_u64 request_id;
    __u32 response_capacity;
    __u32 status;
    __u32 response_length;
    __u32 used_length;
    __aligned_u64 submit_to_callback_ns;
    __aligned_u64 submit_to_return_ns;
    __aligned_u64 completed_callbacks;
    __u8 input[LAB_MAX_PAYLOAD];
    __u8 output[LAB_MAX_PAYLOAD];
};
#define LAB_IOC_INFO _IOR('L', 0, struct lab_info)
#define LAB_IOC_TRANSFER _IOWR('L', 1, struct lab_transfer)
#endif
