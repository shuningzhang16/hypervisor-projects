/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef LAB_PROTOCOL_H
#define LAB_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>

/* Local experiment only. This is NOT an OASIS-assigned device ID. */
#define VIRTIO_LAB_DEVICE_ID 63
#define LAB_VERSION 1
#define LAB_MAX_PAYLOAD 4096
#define LAB_HEADER_SIZE 16
#define LAB_MAX_MESSAGE (LAB_HEADER_SIZE + LAB_MAX_PAYLOAD)
#define LAB_OP_ECHO 1
#define LAB_OK 0
#define LAB_BAD_REQUEST 1
#define LAB_UNSUPPORTED 2
#define LAB_NO_SPACE 3

/* LE wire format; no packed-struct dereferences or host-endian assumptions.
 * Request:  opcode:u16, flags:u16(0), length:u32, request_id:u64, payload.
 * Response: status:u32, length:u32, request_id:u64, payload.
 * Returns actual bytes written; zero means no safe response header fits.
 */
size_t lab_respond(const uint8_t *request, size_t request_len,
                   uint8_t *response, size_t response_capacity);
#endif
