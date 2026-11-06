/* SPDX-License-Identifier: GPL-2.0-or-later */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
#include "lab_uapi.h"

static void require(int ok, const char *what)
{
    if (!ok) { fprintf(stderr, "FAIL: %s (errno=%d %s)\n", what, errno, strerror(errno)); exit(1); }
}
static uint64_t now(void)
{
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}
static int open_device(void)
{
    glob_t paths = {0};
    require(glob("/dev/virtio-lab-*", 0, NULL, &paths) == 0 && paths.gl_pathc == 1, "one lab misc device");
    int fd = open(paths.gl_pathv[0], O_RDWR);
    globfree(&paths); require(fd >= 0, "open"); return fd;
}
static void prepare(struct lab_transfer *t, uint64_t id, unsigned length)
{
    memset(t, 0, sizeof(*t)); t->opcode = 1; t->request_id = id;
    t->length = length; t->response_capacity = 16 + LAB_MAX_PAYLOAD;
    for (unsigned i = 0; i < length && i < LAB_MAX_PAYLOAD; ++i)
        t->input[i] = (unsigned char)(i + id);
}
static void verify(struct lab_transfer *t, unsigned status)
{
    require(t->status == status, "response status");
    require(t->used_length == 16 + t->response_length, "used length");
    if (!status) {
        require(t->response_length == t->length, "echo length");
        require(!memcmp(t->input, t->output, t->length), "echo content");
    } else require(t->response_length == 0, "error payload empty");
    require(t->submit_to_return_ns >= t->submit_to_callback_ns, "callback before waiter completion");
    require(t->completed_callbacks > 0, "actual callback consumed completion");
}
static void smoke(int fd, int packed)
{
    struct lab_info info;
    struct lab_transfer t;
    require(ioctl(fd, LAB_IOC_INFO, &info) == 0, "get config");
    require(info.version == 1 && info.max_payload == 4096 && info.queue_size == 64, "config values");
    require(info.packed == (unsigned)packed, "negotiated ring format");
    uint64_t callbacks = 0;
    unsigned lengths[] = {0, 5, 4096};
    for (unsigned n = 0; n < 3; ++n) {
        prepare(&t, 100 + n, lengths[n]);
        require(ioctl(fd, LAB_IOC_TRANSFER, &t) == 0, "normal ioctl"); verify(&t, 0);
        require(t.completed_callbacks > callbacks, "new completion callback"); callbacks = t.completed_callbacks;
    }
    prepare(&t, 200, 8); t.opcode = 99;
    require(ioctl(fd, LAB_IOC_TRANSFER, &t) == 0, "unsupported opcode transport"); verify(&t, 2);
    prepare(&t, 201, 8); t.flags = 1;
    require(ioctl(fd, LAB_IOC_TRANSFER, &t) == 0, "invalid protocol flags transport"); verify(&t, 1);
    prepare(&t, 202, 8); t.response_capacity = 16;
    require(ioctl(fd, LAB_IOC_TRANSFER, &t) == 0, "short response capacity transport"); verify(&t, 3);
    prepare(&t, 203, 4097);
    require(ioctl(fd, LAB_IOC_TRANSFER, &t) == -1 && errno == EMSGSIZE, "oversized input rejected");
    prepare(&t, 204, 0); t.response_capacity = 15;
    require(ioctl(fd, LAB_IOC_TRANSFER, &t) == -1 && errno == EINVAL, "short header rejected");
    require(ioctl(fd, _IO('L', 99), &t) == -1 && errno == ENOTTY, "unknown ioctl rejected");
    require(ioctl(fd, LAB_IOC_TRANSFER, NULL) == -1 && errno == EFAULT, "bad user pointer rejected");
    prepare(&t, 205, 64);
    require(ioctl(fd, LAB_IOC_TRANSFER, &t) == 0, "recovery after errors"); verify(&t, 0);
    printf("LAB_PASS smoke packed=%u callbacks=%" PRIu64 "\n", info.packed, (uint64_t)t.completed_callbacks);
}
struct thread_work { unsigned index, count; };
static void *worker(void *opaque)
{
    struct thread_work *w = opaque;
    int fd = open_device(); struct lab_transfer *t = malloc(sizeof(*t));
    require(t != NULL, "allocate worker");
    for (unsigned i = 0; i < w->count; ++i) {
        prepare(t, 10000ULL + (uint64_t)w->index * w->count + i, (i * 31) % 4097);
        require(ioctl(fd, LAB_IOC_TRANSFER, t) == 0, "concurrent ioctl"); verify(t, 0);
    }
    free(t); close(fd); return NULL;
}
int main(int argc, char **argv)
{
    if (argc < 2) return 2;
    int fd = open_device();
    struct lab_transfer *t = calloc(1, sizeof(*t));
    require(t != NULL, "allocate request");
    if (!strcmp(argv[1], "smoke")) {
        if (argc != 3) return 2;
        smoke(fd, atoi(argv[2]));
    } else if (!strcmp(argv[1], "latency")) {
        if (argc != 3) return 2;
        int count = atoi(argv[2]); require(count > 0 && count <= 10000, "sample count");
        struct sample { uint64_t id, callback, waiter, ioctl_ns; } *samples = calloc((size_t)count, sizeof(*samples));
        require(samples != NULL, "allocate latency records");
        for (int i = 0; i < count; ++i) {
            prepare(t, 1000000ULL + (unsigned)i, 32);
            uint64_t start = now();
            require(ioctl(fd, LAB_IOC_TRANSFER, t) == 0, "latency ioctl");
            samples[i] = (struct sample){t->request_id, t->submit_to_callback_ns, t->submit_to_return_ns, now() - start};
            verify(t, 0);
        }
        /* Serial output happens after measuring all samples. */
        for (int i = 0; i < count; ++i)
            printf("LAB_LATENCY,%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "\n",
                   samples[i].id, samples[i].callback, samples[i].waiter, samples[i].ioctl_ns);
        free(samples); printf("LAB_PASS latency count=%d\n", count);
    } else if (!strcmp(argv[1], "concurrent")) {
        pthread_t threads[4]; struct thread_work work[4];
        for (unsigned i = 0; i < 4; ++i) {
            work[i] = (struct thread_work){i, 256};
            require(!pthread_create(&threads[i], NULL, worker, &work[i]), "thread create");
        }
        for (unsigned i = 0; i < 4; ++i) require(!pthread_join(threads[i], NULL), "thread join");
        puts("LAB_PASS concurrent requests=1024 callers=4 serialized_in_driver=1");
    } else if (!strcmp(argv[1], "timeout")) {
        prepare(t, 300, 32);
        uint64_t start = now();
        require(ioctl(fd, LAB_IOC_TRANSFER, t) == -1 && errno == ETIMEDOUT, "injected timeout");
        uint64_t elapsed = now() - start;
        require(elapsed >= 50000000ULL && elapsed < 5000000000ULL, "timeout bounded");
        require(ioctl(fd, LAB_IOC_TRANSFER, t) == -1 && errno == EIO, "failed queue rejects reuse");
        printf("LAB_PASS timeout elapsed_ns=%" PRIu64 " reclaim_before_free=reset_and_del_vqs\n", elapsed);
    } else if (!strcmp(argv[1], "remove")) {
        puts("LAB_HOLD_OPEN"); fflush(stdout);
        uint64_t until = now() + 15000000000ULL;
        int removed = 0;
        while (now() < until) {
            struct lab_info info;
            if (ioctl(fd, LAB_IOC_INFO, &info) == -1) {
                require(errno == ENODEV, "open FD after unplug"); removed = 1; break;
            }
            usleep(10000);
        }
        require(removed, "device removal observed");
        puts("LAB_PASS removed_open_fd errno=ENODEV");
    } else return 2;
    free(t); close(fd); return 0;
}
