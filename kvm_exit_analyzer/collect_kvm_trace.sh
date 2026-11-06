#!/usr/bin/env bash
# Records into a separate trace instance. Does not start/restart a VM or workload.
set -euo pipefail
export LC_ALL=C
usage() {
    echo "Usage: sudo bash $0 --pid KVM_PROCESS_PID [--seconds 30] [--output NEW_DIR] [--no-sched] [--signal-start] [--trace-tids ID,ID] [--ready-file NEW_FILE]"
}
pid='' seconds=30 output='' scheduler=1 signal_start=0 trace_tids='' ready_file=''
while (($#)); do
    case $1 in
        --pid|--seconds|--output|--trace-tids|--ready-file)
            (($# >= 2)) || { usage >&2; exit 2; }
            case $1 in --pid) pid=$2;; --seconds) seconds=$2;; --output) output=$2;; --trace-tids) trace_tids=$2;; --ready-file) ready_file=$2;; esac
            shift 2;;
        --no-sched) scheduler=0; shift;;
        --signal-start) signal_start=1; shift;;
        -h|--help) usage; exit 0;;
        *) usage >&2; exit 2;;
    esac
done
[[ $pid =~ ^[1-9][0-9]*$ && $seconds =~ ^[1-9][0-9]*$ ]] || { usage >&2; exit 2; }
[[ -z $trace_tids || $trace_tids =~ ^[1-9][0-9]*(,[1-9][0-9]*)*$ ]] || { usage >&2; exit 2; }
[[ $(uname -s) == Linux && $EUID == 0 ]] || { echo 'Linux/root required for trace recording' >&2; exit 1; }
command -v trace-cmd >/dev/null
[[ -d /proc/$pid/task ]] || { echo 'KVM process not found' >&2; exit 1; }
tracefs=''
for candidate in /sys/kernel/tracing /sys/kernel/debug/tracing; do
    if [[ -r $candidate/available_events ]]; then tracefs=$candidate; break; fi
done
[[ -n $tracefs ]] || { echo 'Readable tracefs required' >&2; exit 1; }
clock=global
if grep -qw mono "$tracefs/trace_clock"; then clock=mono; fi
[[ -n $output ]] || output="runs/kvm-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$(dirname "$output")"
mkdir "$output"  # Never overwrite previous evidence.
exec > >(tee "$output/collection.log") 2>&1
trap 'rc=$?; printf "exit_code=%s\n" "$rc" >> "$output/status.txt"' EXIT
cp "$tracefs/available_events" "$output/available_events.txt"
uname -a > "$output/host.txt"
lscpu >> "$output/host.txt"
trace-cmd --version > "$output/trace-cmd-version.txt" 2>&1 ||
    grep -q '^trace-cmd version ' "$output/trace-cmd-version.txt"
tr '\0' ' ' < "/proc/$pid/cmdline" > "$output/process-command.txt"
printf '\n' >> "$output/process-command.txt"
ps -T -p "$pid" -o pid,tid,psr,comm > "$output/threads.txt"
printf 'requested_seconds=%s\ntrace_clock=%s\nprocess_pid=%s\nstarted_utc=%s\n' "$seconds" "$clock" "$pid" "$(date -u +%FT%TZ)" > "$output/metadata.txt"
tid_filter='' switch_filter='' wake_filter=''
if [[ -n $trace_tids ]]; then
    printf '%s\n' "${trace_tids//,/$'\n'}" > "$output/trace-tids.txt"
else
    for task in /proc/"$pid"/task/*; do echo "${task##*/}"; done > "$output/trace-tids.txt"
fi
while read -r tid; do
    tid_filter+="${tid_filter:+ || }common_pid == $tid"
    switch_filter+="${switch_filter:+ || }prev_pid == $tid || next_pid == $tid"
    wake_filter+="${wake_filter:+ || }pid == $tid"
done < "$output/trace-tids.txt"
events=()
for event in kvm:kvm_entry kvm:kvm_exit kvm:kvm_mmio kvm:kvm_pio; do
    if grep -qx "$event" "$tracefs/available_events"; then
        events+=(-e "$event" -f "$tid_filter")
        printf '%s\n' "$event" >> "$output/selected_events.txt"
        cp "$tracefs/events/${event/:/\/}/format" "$output/${event/:/_}.format"
    else
        echo "Unavailable event: $event"
        case $event in kvm:kvm_entry|kvm:kvm_exit) exit 1;; esac
    fi
done
if ((scheduler)); then
    for name in sched_switch sched_wakeup; do
        event="sched:$name"
        if grep -qx "$event" "$tracefs/available_events"; then
            filter=$switch_filter
            [[ $name != sched_wakeup ]] || filter=$wake_filter
            events+=(-e "$event" -f "$filter")
            echo "$event" >> "$output/selected_events.txt"
            cp "$tracefs/events/sched/$name/format" "$output/$name.format"
        else
            echo "Unavailable event: $event; corresponding metric will be incomplete"
        fi
    done
fi
instance="kvm-lab-$$"
workload=(sleep "$seconds")
if ((signal_start)); then
    # Opt-in for cooperating workloads only. trace-cmd invokes this after enabling events.
    workload=(bash -c 'kill -USR1 "$1"; sleep "$2"' _ "$pid" "$seconds")
elif [[ -n $ready_file ]]; then
    # Executed by trace-cmd only after events are enabled. Never signal QEMU.
    workload=(bash -c 'set -C; printf "ready\n" > "$1"; sleep "$2"' _ "$ready_file" "$seconds")
fi
command=(trace-cmd record -B "$instance" -C "$clock" -b 4096 -o "$output/trace.dat" "${events[@]}" "${workload[@]}")
printf '%q ' "${command[@]}" > "$output/record-command.txt"
printf '\n' >> "$output/record-command.txt"
"${command[@]}"
# -t keeps nanoseconds; -N disables optional plugins for predictable event text.
trace-cmd report -N -t -i "$output/trace.dat" > "$output/trace.txt" 2> "$output/report.stderr"
echo "Saved $output. Review collection.log/report.stderr for lost events."
echo 'New vCPU threads created after collection starts are not in this PID filter.'
