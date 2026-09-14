import os
import subprocess
import shutil
from pathlib import Path

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.oss.discovery.ollama</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>{ollama_path}</string>
        <string>serve</string>
    </array>
    
    <key>KeepAlive</key>
    <true/>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>StandardOutPath</key>
    <string>{log_dir}/ollama.log</string>
    
    <key>StandardErrorPath</key>
    <string>{log_dir}/ollama_error.log</string>
</dict>
</plist>
"""

def get_ollama_plist_path():
    return Path.home() / "Library" / "LaunchAgents" / "com.oss.discovery.ollama.plist"

def install_ollama():
    """Installs the Ollama launchd schedule for the current user."""
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        return False, "Error: 'ollama' executable not found in PATH. Please install Ollama first."
        
    plist_path = get_ollama_plist_path()
    
    log_dir = str((Path.cwd() / "logs").absolute())
    Path(log_dir).mkdir(exist_ok=True)
    
    plist_content = PLIST_TEMPLATE.format(
        ollama_path=ollama_path,
        log_dir=log_dir
    )
    
    # Ensure LaunchAgents dir exists
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(plist_path, "w") as f:
        f.write(plist_content)
        
    # Unload if exists, then load
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    result = subprocess.run(["launchctl", "load", "-w", str(plist_path)], capture_output=True, text=True)
    
    if result.returncode != 0:
        return False, f"Failed to load Ollama service: {result.stderr}"
    
    return True, f"Ollama service installed and started. Plist: {plist_path}"

def remove_ollama():
    """Removes the Ollama launchd schedule."""
    plist_path = get_ollama_plist_path()
    if not plist_path.exists():
        return False, "Ollama service not installed."
        
    subprocess.run(["launchctl", "unload", "-w", str(plist_path)], capture_output=True)
    os.remove(plist_path)
    return True, "Ollama service removed."

def ollama_status():
    """Checks if the Ollama service is installed and running in launchd."""
    plist_path = get_ollama_plist_path()
    if not plist_path.exists():
        return "Not installed."
        
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    if "com.oss.discovery.ollama" in result.stdout:
        return "Installed and running in launchd."
        
    return "Installed (plist exists) but not running in launchd."
