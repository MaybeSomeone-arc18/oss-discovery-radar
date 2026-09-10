import os
import subprocess
from pathlib import Path

HERMES_RETRY_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.oss.discovery.radar.hermes-retries</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
        <string>hermes-retries</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <key>StandardOutPath</key>
    <string>{log_dir}/hermes_retry.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/hermes_retry_error.log</string>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""

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

def get_hermes_retry_plist_path():
    return (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / "com.oss.discovery.radar.hermes-retries.plist"
    )


def install_hermes_retry_schedule(interval_minutes=30):
    """Install the periodic launchd worker for resource-deferred Hermes retries."""
    plist_path = get_hermes_retry_plist_path()
    import sys

    python_path = sys.executable
    working_dir = str(Path.cwd().absolute())
    script_path = str((Path.cwd() / "main.py").absolute())
    log_dir = str((Path.cwd() / "logs").absolute())
    Path(log_dir).mkdir(exist_ok=True)

    plist_content = HERMES_RETRY_PLIST_TEMPLATE.format(
        python_path=python_path,
        script_path=script_path,
        working_dir=working_dir,
        log_dir=log_dir,
        interval_seconds=int(interval_minutes) * 60,
    )

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content)

    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, f"Failed to load Hermes retry schedule: {result.stderr}"

    return (
        True,
        f"Hermes retry schedule installed every {int(interval_minutes)} minutes. "
        f"Plist: {plist_path}",
    )


def remove_hermes_retry_schedule():
    plist_path = get_hermes_retry_plist_path()
    if not plist_path.exists():
        return False, "Hermes retry schedule not installed."

    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )
    os.remove(plist_path)
    return True, "Hermes retry schedule removed."


def hermes_retry_schedule_status():
    plist_path = get_hermes_retry_plist_path()
    if not plist_path.exists():
        return "Hermes retry schedule not installed."

    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
    )
    if "com.oss.discovery.radar.hermes-retries" in result.stdout:
        return "Hermes retry schedule installed and loaded in launchd."
    return "Hermes retry plist exists but is not loaded in launchd."


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


def process_due_hermes_retries(limit=10):
    """Retry resource-deferred Hermes runs whose retry time has arrived."""
    from src.opportunity_manager import get_due_hermes_retries, clear_hermes_retry, schedule_hermes_retry
    from src.autonomous_contributor import run_autonomous_by_url

    rows = get_due_hermes_retries(limit=limit)
    results = []

    for row in rows:
        issue_url = row["url"]

        try:
            package = run_autonomous_by_url(issue_url)

            if package is not None:
                clear_hermes_retry(issue_url)
                results.append(
                    {
                        "url": issue_url,
                        "result": "success",
                        "package": str(package),
                    }
                )
            else:
                schedule_hermes_retry(issue_url)
                results.append(
                    {
                        "url": issue_url,
                        "result": "deferred",
                    }
                )
        except Exception as exc:
            schedule_hermes_retry(issue_url)
            results.append(
                {
                    "url": issue_url,
                    "result": "failed",
                    "error": str(exc),
                }
            )

    return results
