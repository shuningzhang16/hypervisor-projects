/* Ordinary Linux userspace workloads. No custom kernel/Guest driver. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static uint64_t now(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}
static void fail(const char *s) { perror(s); exit(1); }
struct cpu_work { uint64_t until, iterations, result; };
static void *cpu(void *arg) {
    struct cpu_work *w = arg;
    uint64_t x = 1, n = 0;
    do {
        for (unsigned i = 0; i < 200000; ++i) x = (x * 1664525 + 1013904223) ^ (x >> 17);
        n += 200000;
    } while (now() < w->until);
    w->iterations = n; w->result = x; return NULL;
}
static void transfer(int fd, void *buffer, size_t size, int sending) {
    size_t done = 0;
    while (done < size) {
        ssize_t n = sending ? send(fd, (char *)buffer + done, size - done, MSG_NOSIGNAL)
                            : recv(fd, (char *)buffer + done, size - done, 0);
        if (n <= 0) fail("TCP transfer");
        done += (size_t)n;
    }
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    int seconds = atoi(argv[2]), parameter = atoi(argv[3]);
    if (seconds < 1 || seconds > 60) return 2;
    uint64_t start = now(), until = start + (uint64_t)seconds * 1000000000ULL, units = 0;
    const char *unit;
    if (!strcmp(argv[1], "cpu")) {
        if (parameter < 1 || parameter > 16) return 2;
        pthread_t threads[16]; struct cpu_work work[16] = {{0}};
        for (int i = 0; i < parameter; ++i) {
            work[i].until = until;
            if (pthread_create(&threads[i], NULL, cpu, &work[i])) fail("pthread_create");
        }
        for (int i = 0; i < parameter; ++i) {
            pthread_join(threads[i], NULL); units += work[i].iterations;
            /* Printing the result prevents the compiler eliminating the work. */
            fprintf(stderr, "cpu_result[%d]=%llu\n", i, (unsigned long long)work[i].result);
        }
        unit = "iterations";
    } else if (!strcmp(argv[1], "disk")) {
        int fd = open("/data/work.bin", O_CREAT | O_RDWR | O_DIRECT | O_TRUNC, 0600);
        if (fd < 0) fail("open scratch file");
        void *out, *in;
        if (posix_memalign(&out, 4096, 65536) || posix_memalign(&in, 4096, 65536)) return 1;
        memset(out, 0x5a, 65536);
        unsigned block = 0;
        do {
            off_t offset = (off_t)(block++ % 512) * 65536;
            ((unsigned char *)out)[0] = (unsigned char)block;
            if (pwrite(fd, out, 65536, offset) != 65536 || fdatasync(fd)) fail("disk write/sync");
            if (pread(fd, in, 65536, offset) != 65536) fail("disk read");
            if (memcmp(in, out, 65536)) { fprintf(stderr, "disk mismatch\n"); return 1; }
            units += 65536;
        } while (now() < until);
        free(out); free(in); close(fd); unit = "verified_write_bytes";
    } else if (!strcmp(argv[1], "net")) {
        if (parameter < 1 || parameter > 65535) return 2;
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) fail("socket");
        struct timeval timeout = {.tv_sec = 10};
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons((uint16_t)parameter)};
        inet_pton(AF_INET, "10.0.2.2", &addr.sin_addr);
        if (connect(fd, (struct sockaddr *)&addr, sizeof(addr))) fail("connect");
        unsigned char out[65536], in[65536]; memset(out, 0x6b, sizeof(out));
        do {
            out[0] = (unsigned char)(units / sizeof(out));
            transfer(fd, out, sizeof(out), 1); transfer(fd, in, sizeof(in), 0);
            if (memcmp(out, in, sizeof(out))) { fprintf(stderr, "TCP echo mismatch\n"); return 1; }
            units += sizeof(out);
        } while (now() < until);
        close(fd); unit = "verified_echo_bytes";
    } else return 2;
    uint64_t elapsed = now() - start;
    printf("{\"mode\":\"%s\",\"units\":%llu,\"unit\":\"%s\",\"elapsed_ns\":%llu,\"rate\":%.3f}\n",
           argv[1], (unsigned long long)units, unit, (unsigned long long)elapsed,
           (double)units * 1e9 / (double)elapsed);
    return 0;
}
