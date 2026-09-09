import os
import re
import shutil
import subprocess
import sys


def get_available_memory_mb():
    """Return approximate available memory on macOS in MB."""
    if sys.platform != "darwin":
        return 8192

    try:
        vm = subprocess.check_output(["vm_stat"], text=True)

        match = re.search(r"page size of (\d+) bytes", vm)
        page_size = int(match.group(1)) if match else os.sysconf("SC_PAGE_SIZE")

        free_pages = 0
        inactive_pages = 0

        for line in vm.splitlines():
            if "Pages free:" in line:
                free_pages = int(line.split(":")[1].strip().rstrip("."))
            elif "Pages inactive:" in line:
                inactive_pages = int(line.split(":")[1].strip().rstrip("."))

        return (free_pages + inactive_pages) * page_size / (1024 * 1024)

    except Exception:
        return 8192


def check_resources_for_hermes(min_memory_mb=4096, min_disk_mb=2048):
    """Return (True, message) when resources are sufficient for Hermes."""
    avail_mem = get_available_memory_mb()

    if avail_mem < min_memory_mb:
        return (
            False,
            f"Insufficient memory. Available: {avail_mem:.0f}MB, "
            f"Required: {min_memory_mb}MB",
        )

    _, _, free = shutil.disk_usage("/")
    free_mb = free / (1024 * 1024)

    if free_mb < min_disk_mb:
        return (
            False,
            f"Insufficient disk space. Available: {free_mb:.0f}MB, "
            f"Required: {min_disk_mb}MB",
        )

    return True, "Resources sufficient"
