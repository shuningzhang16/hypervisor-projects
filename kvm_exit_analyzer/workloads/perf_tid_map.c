/* Map namespace-local TIDs to tracepoint common_pid; Linux x86-64 userspace. */
#define _GNU_SOURCE
#include <errno.h>
#include <linux/perf_event.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

static void fail(const char *message) { perror(message); exit(1); }
int main(int argc, char **argv)
{
    if (argc < 4 || argc > 35) {
        fprintf(stderr, "usage: perf_tid_map TRACEPOINT_ID COMMON_PID_OFFSET TID...\n");
        return 2;
    }
    struct pollfd fds[32] = {0};
    struct perf_event_mmap_page *pages[32];
    int tids[32], maps[32] = {0};
    size_t page = (size_t)sysconf(_SC_PAGESIZE), length = page * 33;
    unsigned offset = (unsigned)strtoul(argv[2], NULL, 10);
    int count = argc - 3;
    for (int i = 0; i < count; ++i) {
        tids[i] = atoi(argv[i + 3]);
        if (tids[i] <= 0 || offset > 128) return 2;
        struct perf_event_attr attr = {
            .type = PERF_TYPE_TRACEPOINT, .size = sizeof(attr),
            .config = strtoull(argv[1], NULL, 10), .sample_period = 1,
            .sample_type = PERF_SAMPLE_RAW, .disabled = 1, .wakeup_events = 1,
        };
        fds[i].fd = (int)syscall(SYS_perf_event_open, &attr, tids[i], -1, -1,
                               PERF_FLAG_FD_CLOEXEC);
        fds[i].events = POLLIN;
        if (fds[i].fd < 0) fail("perf_event_open");
        pages[i] = mmap(NULL, length, PROT_READ | PROT_WRITE, MAP_SHARED, fds[i].fd, 0);
        if (pages[i] == MAP_FAILED) fail("mmap");
        if (ioctl(fds[i].fd, PERF_EVENT_IOC_ENABLE, 0)) fail("enable");
    }
    puts("{\"ready\":true}"); fflush(stdout);
    for (int left = count; left > 0;) {
        if (poll(fds, (nfds_t)count, 10000) <= 0) fail("poll timeout/error");
        for (int i = 0; i < count; ++i) {
            if (maps[i] || !(fds[i].revents & POLLIN)) continue;
            if (ioctl(fds[i].fd, PERF_EVENT_IOC_DISABLE, 0)) fail("disable");
            uint64_t head = __atomic_load_n(&pages[i]->data_head, __ATOMIC_ACQUIRE);
            uint64_t size = pages[i]->data_size, start = pages[i]->data_offset;
            if (!size || head > size || start + size > length) {
                fprintf(stderr, "mapping sample ring overflow/invalid\n"); return 1;
            }
            const unsigned char *data = (unsigned char *)pages[i] + start;
            uint64_t cursor = 0;
            while (cursor + sizeof(struct perf_event_header) <= head) {
                struct perf_event_header h;
                memcpy(&h, data + cursor, sizeof(h));
                if (h.size < sizeof(h) || cursor + h.size > head) return 1;
                if (h.type == PERF_RECORD_SAMPLE && h.size >= 12) {
                    uint32_t raw_size; int pid;
                    memcpy(&raw_size, data + cursor + 8, 4);
                    if (raw_size < offset + 4 || 12U + raw_size > h.size) return 1;
                    memcpy(&pid, data + cursor + 12 + offset, 4);
                    if (pid <= 0 || (maps[i] && maps[i] != pid)) return 1;
                    maps[i] = pid;
                }
                cursor += h.size;
            }
            if (!maps[i]) { fprintf(stderr, "no raw PID sample\n"); return 1; }
            close(fds[i].fd); fds[i].fd = -1;
            munmap(pages[i], length); --left;
        }
    }
    printf("{\"mapping\":{");
    for (int i = 0; i < count; ++i)
        printf("%s\"%d\":%d", i ? "," : "", tids[i], maps[i]);
    puts("}}");
    return 0;
}
