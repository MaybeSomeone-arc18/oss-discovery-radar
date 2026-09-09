import subprocess
import shutil
import sys

def get_available_memory_mb():
    """Returns approximate available memory on macOS in MB using vm_stat"""
    if sys.platform != "darwin":
        return 8192 # Default if not mac
    try:
        page_size = 4096
        vm = subprocess.check_output(['vm_stat'], text=True)
        free_pages = 0
        inactive_pages = 0
        for line in vm.split('\n'):
            if 'Pages free:' in line:
                free_pages = int(line.split(':')[1].strip().rstrip('.'))
            elif 'Pages inactive:' in line:
                inactive_pages = int(line.split(':')[1].strip().rstrip('.'))
        
        available_mb = (free_pages + inactive_pages) * page_size / (1024 * 1024)
        return available_mb
    except Exception:
        return 8192

def check_resources_for_hermes(min_memory_mb=4096, min_disk_mb=2048):
    """
    Checks if resources are sufficient to run a heavy Hermes/LLM workload.
    Returns (True, "Ready") or (False, "Reason")
    """
    # Memory check
    avail_mem = get_available_memory_mb()
    if avail_mem < min_memory_mb:
        return False, f"Insufficient memory. Available: {avail_mem:.0f}MB, Required: {min_memory_mb}MB"
        
    # Disk check
    total, used, free = shutil.disk_usage("/")
    free_mb = free / (1024 * 1024)
    if free_mb < min_disk_mb:
        return False, f"Insufficient disk space. Available: {free_mb:.0f}MB, Required: {min_disk_mb}MB"
        
    return True, "Resources sufficient"
