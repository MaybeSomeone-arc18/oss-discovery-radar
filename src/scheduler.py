import os
import subprocess
from pathlib import Path

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.oss.discovery.radar</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
        <string>run-now</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    
    <key>StandardOutPath</key>
    <string>{log_dir}/radar.log</string>
    
    <key>StandardErrorPath</key>
    <string>{log_dir}/radar_error.log</string>
    
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""

def get_plist_path():
    return Path.home() / "Library" / "LaunchAgents" / "com.oss.discovery.radar.plist"

def install_schedule(hour=2, minute=0):
    """Installs the daily schedule for macOS launchd."""
    plist_path = get_plist_path()
    
    import sys
    python_path = sys.executable
    working_dir = str(Path.cwd().absolute())
    script_path = str((Path.cwd() / "main.py").absolute())
    log_dir = str((Path.cwd() / "logs").absolute())
    
    Path(log_dir).mkdir(exist_ok=True)
    
    plist_content = PLIST_TEMPLATE.format(
        python_path=python_path,
        script_path=script_path,
        working_dir=working_dir,
        log_dir=log_dir,
        hour=hour,
        minute=minute
    )
    
    # Ensure LaunchAgents dir exists
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(plist_path, "w") as f:
        f.write(plist_content)
        
    # Unload if exists, then load
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    result = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, text=True)
    
    if result.returncode != 0:
        return False, f"Failed to load schedule: {result.stderr}"
    
    return True, f"Schedule installed at {hour:02d}:{minute:02d} daily. Plist: {plist_path}"

def remove_schedule():
    """Removes the daily schedule."""
    plist_path = get_plist_path()
    if not plist_path.exists():
        return False, "Schedule not installed."
        
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    os.remove(plist_path)
    return True, "Schedule removed."

def schedule_status():
    """Checks if the schedule is installed and running in launchd."""
    plist_path = get_plist_path()
    if not plist_path.exists():
        return "Not installed."
        
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    if "com.oss.discovery.radar" in result.stdout:
        return "Installed and loaded in launchd."
        
    return "Installed (plist exists) but not loaded in launchd."
