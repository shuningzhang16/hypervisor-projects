/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "lab-protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    uint8_t req[LAB_MAX_MESSAGE] = {LAB_OP_ECHO};
    uint8_t res[LAB_MAX_MESSAGE + 1];
    size_t used;
    req[4] = 3;
    req[8] = 42;
    memcpy(req + 16, "abc", 3);
    memset(res, 0xa5, sizeof(res));
    used = lab_respond(req, 19, res, 19);
    assert(used == 19 && res[0] == LAB_OK && res[4] == 3 && res[8] == 42);
    assert(memcmp(res + 16, "abc", 3) == 0 && res[19] == 0xa5);
    assert(lab_respond(req, 19, res, 15) == 0);
    used = lab_respond(req, 19, res, 16);
    assert(used == 16 && res[0] == LAB_NO_SPACE && res[4] == 0);
    req[0] = 99;
    assert(lab_respond(req, 19, res, sizeof(res)) == 16 && res[0] == LAB_UNSUPPORTED);
    req[0] = LAB_OP_ECHO;
    req[2] = 1;
    assert(lab_respond(req, 19, res, sizeof(res)) == 16 && res[0] == LAB_BAD_REQUEST);
    req[2] = 0;
    assert(lab_respond(req, 18, res, sizeof(res)) == 16 && res[0] == LAB_BAD_REQUEST);
    assert(lab_respond(req, 20, res, sizeof(res)) == 16 && res[0] == LAB_BAD_REQUEST);
    assert(lab_respond(req, 1, res, sizeof(res)) == 16 && res[0] == LAB_BAD_REQUEST);
    memset(req + 4, 0xff, 4);
    assert(lab_respond(req, sizeof(req), res, sizeof(res)) == 16 && res[0] == LAB_BAD_REQUEST);
    req[4] = 0; req[5] = 16; req[6] = 0; req[7] = 0;
    memset(req + 16, 0x5a, LAB_MAX_PAYLOAD);
    assert(lab_respond(req, sizeof(req), res, sizeof(res)) == LAB_MAX_MESSAGE);
    assert(memcmp(req + 16, res + 16, LAB_MAX_PAYLOAD) == 0);
    req[5] = 0;
    assert(lab_respond(req, 16, res, sizeof(res)) == 16 && res[0] == LAB_OK);
    /* Deterministic varied payloads: verify round-trip bytes and untouched tail. */
    for (unsigned n = 0; n < 10000; n++) {
        unsigned length = (n * 7919u) % (LAB_MAX_PAYLOAD + 1);
        memset(req, 0, 16);
        req[0] = LAB_OP_ECHO;
        req[4] = length; req[5] = length >> 8;
        for (unsigned i = 0; i < length; i++) { req[16 + i] = (uint8_t)(n + i * 31); }
        memset(res, 0xa5, sizeof(res));
        used = lab_respond(req, 16 + length, res, 16 + length);
        assert(used == 16 + length && res[0] == LAB_OK);
        assert(memcmp(req + 16, res + 16, length) == 0);
        assert(res[used] == 0xa5);
    }
    puts("PASS: 10000 varied-length payload round trips with untouched-tail checks");
    puts("PASS: echo, empty/max payload, short buffers, unsupported opcode, flags, length/overflow");
    return 0;
}
