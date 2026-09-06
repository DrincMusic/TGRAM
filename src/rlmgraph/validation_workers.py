from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import ValidationWorkerLimits


@dataclass
class BoundedProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    observed_processes: int
    peak_memory_bytes: int
    output_bytes: int
    failure_reason: str | None = None


class BoundedValidationRunner:
    """Execute one allowlisted command without a shell and monitor its process tree."""

    def __init__(
        self,
        resource_probe: Callable[[int], tuple[int, int, list[int]]] | None = None,
    ) -> None:
        self.resource_probe = resource_probe or _process_tree_resources

    def execute(
        self, command: list[str], cwd: Path, limits: ValidationWorkerLimits
    ) -> BoundedProcessResult:
        started = time.perf_counter()
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["RLMGRAPH_MAX_PROCESSES"] = str(limits.max_processes)
        environment["RLMGRAPH_MAX_MEMORY_BYTES"] = str(limits.max_memory_bytes)
        environment["RLMGRAPH_VALIDATION_ROOT"] = str(cwd)
        observed_processes = 0
        peak_memory = 0
        failure = None
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                ),
            )
            while process.poll() is None:
                elapsed = time.perf_counter() - started
                count, memory, descendants = self.resource_probe(process.pid)
                observed_processes = max(observed_processes, count)
                peak_memory = max(peak_memory, memory)
                if elapsed > limits.max_wall_time_seconds:
                    failure = "Validation worker exceeded its wall-time limit."
                elif count > limits.max_processes:
                    failure = "Validation worker exceeded its process-count limit."
                elif memory > limits.max_memory_bytes:
                    failure = "Validation worker exceeded its memory limit."
                if failure:
                    _terminate_tree(process, descendants)
                    break
                time.sleep(0.01)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _terminate_tree(process, [])
                process.wait(timeout=2)
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout_bytes = stdout_file.read(limits.max_output_bytes + 1)
            stderr_bytes = stderr_file.read(limits.max_output_bytes + 1)
        output_bytes = len(stdout_bytes) + len(stderr_bytes)
        if output_bytes > limits.max_output_bytes and failure is None:
            failure = "Validation worker exceeded its output-size limit."
        remaining = limits.max_output_bytes
        stdout_bytes = stdout_bytes[:remaining]
        remaining -= len(stdout_bytes)
        stderr_bytes = stderr_bytes[:remaining]
        exit_code = process.returncode if process.returncode is not None else 125
        if failure and exit_code == 0:
            exit_code = 125
        return BoundedProcessResult(
            exit_code=exit_code,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_ms=(time.perf_counter() - started) * 1000,
            observed_processes=max(1, observed_processes),
            peak_memory_bytes=peak_memory,
            output_bytes=output_bytes,
            failure_reason=failure,
        )


def _terminate_tree(process: subprocess.Popen, descendants: list[int]) -> None:
    for pid in reversed(descendants):
        try:
            if sys.platform == "win32":
                _terminate_windows_pid(pid)
            else:
                os.kill(pid, 9)
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def _process_tree_resources(root_pid: int) -> tuple[int, int, list[int]]:
    return _windows_process_tree_resources(root_pid) if sys.platform == "win32" else _proc_resources(root_pid)


def _proc_resources(root_pid: int) -> tuple[int, int, list[int]]:
    proc = Path("/proc")
    parents: dict[int, int] = {}
    memory: dict[int, int] = {}
    if not proc.exists():
        return 1, 0, []
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            fields = (item / "stat").read_text().split()
            pid, parents[int(item.name)] = int(item.name), int(fields[3])
            pages = int((item / "statm").read_text().split()[1])
            memory[pid] = pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            continue
    descendants = []
    frontier = [root_pid]
    while frontier:
        parent = frontier.pop()
        children = [pid for pid, ppid in parents.items() if ppid == parent and pid not in descendants]
        descendants.extend(children)
        frontier.extend(children)
    pids = [root_pid, *descendants]
    return len(pids), sum(memory.get(pid, 0) for pid in pids), descendants


def _windows_process_tree_resources(root_pid: int) -> tuple[int, int, list[int]]:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    parents: dict[int, int] = {}
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    if snapshot not in {0, -1} and kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
        while True:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        kernel32.CloseHandle(snapshot)
    descendants = []
    frontier = [root_pid]
    while frontier:
        parent = frontier.pop()
        children = [pid for pid, ppid in parents.items() if ppid == parent and pid not in descendants]
        descendants.extend(children)
        frontier.extend(children)
    pids = [root_pid, *descendants]
    return len(pids), sum(_windows_rss(pid) for pid in pids), descendants


def _windows_rss(pid: int) -> int:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return 0
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    kernel32.CloseHandle(handle)
    return int(counters.WorkingSetSize) if ok else 0


def _terminate_windows_pid(pid: int) -> None:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x0001, False, pid)
    if handle:
        kernel32.TerminateProcess(handle, 125)
        kernel32.CloseHandle(handle)
