/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "lab-protocol.h"
#include <string.h>

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void put32(uint8_t *p, uint32_t value)
{
    p[0] = value;
    p[1] = value >> 8;
    p[2] = value >> 16;
    p[3] = value >> 24;
}

size_t lab_respond(const uint8_t *request, size_t request_len,
                   uint8_t *response, size_t response_capacity)
{
    uint32_t length = 0, status = LAB_OK;
    if (response_capacity < LAB_HEADER_SIZE) {
        return 0;
    }
    memset(response, 0, LAB_HEADER_SIZE);
    if (request_len < LAB_HEADER_SIZE) {
        status = LAB_BAD_REQUEST;
    } else {
        memcpy(response + 8, request + 8, 8);
        length = get32(request + 4);
        if (length > LAB_MAX_PAYLOAD || request_len != LAB_HEADER_SIZE + length ||
            request[2] != 0 || request[3] != 0) {
            status = LAB_BAD_REQUEST;
        } else if (request[0] != LAB_OP_ECHO || request[1] != 0) {
            status = LAB_UNSUPPORTED;
        } else if (response_capacity - LAB_HEADER_SIZE < length) {
            status = LAB_NO_SPACE;
        }
    }
    if (status != LAB_OK) {
        length = 0;
    }
    put32(response, status);
    put32(response + 4, length);
    if (length) {
        memcpy(response + LAB_HEADER_SIZE, request + LAB_HEADER_SIZE, length);
    }
    return LAB_HEADER_SIZE + length;
}
