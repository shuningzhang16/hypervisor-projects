/* SPDX-License-Identifier: GPL-2.0-or-later
 * Userspace-only KVM workload. No kernel module or Guest driver.
 * Emits controlled CPU+PIO, PIO or MMIO exits for trace validation.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/kvm.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define MAX_VCPUS 4
#define RAM_SIZE 0x10000
#define CODE_GPA 0x1000

struct worker {
    int index, tid, error;
    uint64_t io_exits, mmio_exits, elapsed_ns;
};
static int vm_fd, kvm_fd, run_size, vcpus = 1, seconds = 2, wait_signal;
static unsigned delay_ms = 1000, pause_us = 1000;
static uint64_t start_ns;
static pthread_barrier_t barrier;
static const char *trace_marker;

static uint64_t now_ns(void)
{
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return (uint64_t)time.tv_sec * 1000000000 + time.tv_nsec;
}

static void sleep_ns(uint64_t duration)
{
    struct timespec ts = {duration / 1000000000, duration % 1000000000};
    while (nanosleep(&ts, &ts) && errno == EINTR) { }
}

static void *run_vcpu(void *arg)
{
    struct worker *w = arg;
    struct kvm_sregs sregs;
    struct kvm_regs regs = {.rip = CODE_GPA, .rflags = 2, .rsp = 0x8000};
    struct kvm_run *run = MAP_FAILED;
    int fd = -1;
    char name[16];
    snprintf(name, sizeof(name), "lab-vcpu-%d", w->index);
    pthread_setname_np(pthread_self(), name);
    w->tid = (int)syscall(SYS_gettid);
    if (trace_marker) {
        char marker[64];
        int marker_fd = open(trace_marker, O_WRONLY | O_CLOEXEC);
        int length = snprintf(marker, sizeof(marker), "hypervisor_tid=%d", w->tid);
        if (marker_fd < 0 || write(marker_fd, marker, length) != length) {
            perror("trace marker"); w->error = 1;
        }
        if (marker_fd >= 0) { close(marker_fd); }
    }
    fd = ioctl(vm_fd, KVM_CREATE_VCPU, w->index);
    if (fd < 0) { perror("KVM_CREATE_VCPU"); w->error = 1; goto ready; }
    run = mmap(NULL, run_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (run == MAP_FAILED) { perror("mmap kvm_run"); w->error = 1; goto ready; }
    if (ioctl(fd, KVM_GET_SREGS, &sregs)) {
        perror("KVM_GET_SREGS"); w->error = 1; goto ready;
    }
    sregs.cs.base = 0;
    sregs.cs.selector = 0;
    if (ioctl(fd, KVM_SET_SREGS, &sregs) || ioctl(fd, KVM_SET_REGS, &regs)) {
        perror("KVM_SET_REGS/SREGS"); w->error = 1;
    }
ready:
    pthread_barrier_wait(&barrier);
    pthread_barrier_wait(&barrier);
    if (!w->error) {
        uint64_t now = now_ns();
        if (now < start_ns) { sleep_ns(start_ns - now); }
        const uint64_t began = now_ns();
        const uint64_t deadline = began + (uint64_t)seconds * 1000000000;
        while (now_ns() < deadline) {
            if (ioctl(fd, KVM_RUN, 0) < 0) {
                if (errno == EINTR) { continue; }
                perror("KVM_RUN"); w->error = 1; break;
            }
            if (run->exit_reason == KVM_EXIT_IO && run->io.port == 0xe9 &&
                run->io.direction == KVM_EXIT_IO_OUT && run->io.size == 1) {
                w->io_exits++;
            } else if (run->exit_reason == KVM_EXIT_MMIO &&
                       run->mmio.phys_addr >= 0xa0000 && run->mmio.phys_addr < 0xa0010 &&
                       run->mmio.len == 1) {
                if (!run->mmio.is_write) { run->mmio.data[0] = 0x5a; }
                w->mmio_exits++;
            } else {
                fprintf(stderr, "vcpu=%d unexpected KVM exit=%u\n", w->index, run->exit_reason);
                w->error = 1; break;
            }
            if (pause_us) { sleep_ns((uint64_t)pause_us * 1000); }
        }
        w->elapsed_ns = now_ns() - began;
    }
    if (run != MAP_FAILED) { munmap(run, run_size); }
    if (fd >= 0) { close(fd); }
    return NULL;
}

static unsigned number(const char *text, unsigned min, unsigned max)
{
    char *end;
    unsigned long value = strtoul(text, &end, 10);
    if (!*text || *end || value < min || value > max) {
        fprintf(stderr, "invalid numeric argument: %s\n", text);
        exit(2);
    }
    return value;
}

int main(int argc, char **argv)
{
    const char *mode = "cpu";
    /* Real-mode instruction streams. CPU performs 60000 decrements per PIO.
     * MMIO addresses 0xa0000/1 are intentionally outside the 64 KiB RAM slot. */
    const uint8_t cpu[] = {0xb9,0x60,0xea,0x49,0x75,0xfd,0xba,0xe9,0,0xb0,0x2a,0xee,0xeb,0xf2};
    const uint8_t pio[] = {0xba,0xe9,0,0xb0,0x2a,0xee,0xeb,0xfd};
    const uint8_t mmio[] = {0xb8,0,0xa0,0x8e,0xd8,0xa0,0,0,0xa2,1,0,0xeb,0xf8};
    const uint8_t *code;
    size_t code_size;
    pthread_t threads[MAX_VCPUS];
    struct worker workers[MAX_VCPUS] = {0};
    int result = 0;
    sigset_t start_set;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 == argc) { fprintf(stderr, "option requires value\n"); return 2; }
        if (!strcmp(argv[i], "--mode")) { mode = argv[i + 1]; }
        else if (!strcmp(argv[i], "--vcpus")) { vcpus = number(argv[i + 1], 1, MAX_VCPUS); }
        else if (!strcmp(argv[i], "--seconds")) { seconds = number(argv[i + 1], 1, 30); }
        else if (!strcmp(argv[i], "--delay-ms")) { delay_ms = number(argv[i + 1], 0, 10000); }
        else if (!strcmp(argv[i], "--pause-us")) { pause_us = number(argv[i + 1], 0, 1000000); }
        else if (!strcmp(argv[i], "--wait-signal")) { wait_signal = number(argv[i + 1], 0, 1); }
        else if (!strcmp(argv[i], "--trace-marker")) { trace_marker = argv[i + 1]; }
        else { fprintf(stderr, "unknown option: %s\n", argv[i]); return 2; }
    }
    if (!strcmp(mode, "cpu")) { code = cpu; code_size = sizeof(cpu); }
    else if (!strcmp(mode, "pio")) { code = pio; code_size = sizeof(pio); }
    else if (!strcmp(mode, "mmio")) { code = mmio; code_size = sizeof(mmio); }
    else { fprintf(stderr, "mode must be cpu, pio, or mmio\n"); return 2; }
    sigemptyset(&start_set);
    sigaddset(&start_set, SIGUSR1);
    if (wait_signal && pthread_sigmask(SIG_BLOCK, &start_set, NULL)) { return 1; }
    kvm_fd = open("/dev/kvm", O_RDWR | O_CLOEXEC);
    if (kvm_fd < 0) { perror("/dev/kvm"); return 1; }
    if (ioctl(kvm_fd, KVM_GET_API_VERSION, 0) != 12) { fprintf(stderr, "KVM API != 12\n"); return 1; }
    vm_fd = ioctl(kvm_fd, KVM_CREATE_VM, 0);
    if (vm_fd < 0) { perror("KVM_CREATE_VM"); return 1; }
    if (ioctl(vm_fd, KVM_SET_TSS_ADDR, 0xfffbd000UL) < 0) { perror("KVM_SET_TSS_ADDR"); return 1; }
    run_size = ioctl(kvm_fd, KVM_GET_VCPU_MMAP_SIZE, 0);
    if (run_size < (int)sizeof(struct kvm_run)) { fprintf(stderr, "invalid kvm_run size\n"); return 1; }
    void *ram = mmap(NULL, RAM_SIZE, PROT_READ | PROT_WRITE, MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
    if (ram == MAP_FAILED) { perror("mmap RAM"); return 1; }
    memcpy((uint8_t *)ram + CODE_GPA, code, code_size);
    struct kvm_userspace_memory_region region = {
        .slot = 0, .guest_phys_addr = 0, .memory_size = RAM_SIZE, .userspace_addr = (uintptr_t)ram,
    };
    if (ioctl(vm_fd, KVM_SET_USER_MEMORY_REGION, &region)) { perror("KVM_SET_USER_MEMORY_REGION"); return 1; }
    if (pthread_barrier_init(&barrier, NULL, vcpus + 1)) { return 1; }
    for (int i = 0; i < vcpus; i++) {
        workers[i].index = i;
        if (pthread_create(&threads[i], NULL, run_vcpu, &workers[i])) {
            /* Process exit releases VM fds; do not leave existing workers waiting. */
            fprintf(stderr, "pthread_create failed\n"); exit(1);
        }
    }
    pthread_barrier_wait(&barrier);
    printf("{\"state\":\"ready\",\"pid\":%d,\"tids\":[", getpid());
    for (int i = 0; i < vcpus; i++) { printf("%s%d", i ? "," : "", workers[i].tid); }
    puts("]}"); fflush(stdout);
    if (wait_signal) {
        int received;
        if (sigwait(&start_set, &received)) { fprintf(stderr, "sigwait failed\n"); exit(1); }
    }
    start_ns = now_ns() + (uint64_t)delay_ms * 1000000;
    pthread_barrier_wait(&barrier);
    for (int i = 0; i < vcpus; i++) { pthread_join(threads[i], NULL); result |= workers[i].error; }
    printf("{\"state\":\"finished\",\"mode\":\"%s\",\"vcpus\":%d,\"pause_us\":%u,\"workers\":[", mode, vcpus, pause_us);
    for (int i = 0; i < vcpus; i++) {
        struct worker *w = &workers[i];
        printf("%s{\"tid\":%d,\"io_exits\":%llu,\"mmio_exits\":%llu,\"elapsed_ns\":%llu,\"error\":%d}",
               i ? "," : "", w->tid, (unsigned long long)w->io_exits, (unsigned long long)w->mmio_exits,
               (unsigned long long)w->elapsed_ns, w->error);
    }
    puts("]}");
    pthread_barrier_destroy(&barrier);
    close(vm_fd); close(kvm_fd); munmap(ram, RAM_SIZE);
    return result;
}
