import json
import time
import os
from pathlib import Path

REGISTRY_PATH = Path(os.environ.get("RADAR_DATA_DIR", "data")) / "implementation_registry.json"

INITIAL_MODELS = [
    {
        "model_id": "free-coding-test",
        "provider": "omniroute",
        "free_only": True,
        "verified_tool_capable": True,
        "verified_filesystem_edit": True,
        "sandbox_verified": True,
        "measured_latency": 18.84,
        "availability_status": "AVAILABLE",
        "cooldown_until": 0,
        "last_probe": time.time(),
        "failure_count": 0,
        "last_failure_type": None,
        "last_success": time.time(),
    },
    {
        "model_id": "opencode-zen/ling-3.0-flash-fin-free",
        "provider": "omniroute",
        "free_only": True,
        "verified_tool_capable": True,
        "verified_filesystem_edit": True,
        "sandbox_verified": True,
        "measured_latency": 20.85,
        "availability_status": "AVAILABLE",
        "cooldown_until": 0,
        "last_probe": time.time(),
        "failure_count": 0,
        "last_failure_type": None,
        "last_success": time.time(),
    },
    {
        "model_id": "auto/coding:free",
        "provider": "omniroute",
        "free_only": True,
        "verified_tool_capable": True,
        "verified_filesystem_edit": True,
        "sandbox_verified": True,
        "measured_latency": 24.50,
        "availability_status": "AVAILABLE",
        "cooldown_until": 0,
        "last_probe": time.time(),
        "failure_count": 0,
        "last_failure_type": None,
        "last_success": time.time(),
    },
    {
        "model_id": "auto/best-free",
        "provider": "omniroute",
        "free_only": True,
        "verified_tool_capable": True,
        "verified_filesystem_edit": True,
        "sandbox_verified": True,
        "measured_latency": 27.57,
        "availability_status": "AVAILABLE",
        "cooldown_until": 0,
        "last_probe": time.time(),
        "failure_count": 0,
        "last_failure_type": None,
        "last_success": time.time(),
    },
    {
        "model_id": "opencode-zen/mimo-v2.5-free",
        "provider": "omniroute",
        "free_only": True,
        "verified_tool_capable": True,
        "verified_filesystem_edit": True,
        "sandbox_verified": True,
        "measured_latency": 42.99,
        "availability_status": "AVAILABLE",
        "cooldown_until": 0,
        "last_probe": time.time(),
        "failure_count": 0,
        "last_failure_type": None,
        "last_success": time.time(),
    },
    {
        "model_id": "oc/mimo-v2.5-free",
        "provider": "omniroute",
        "free_only": True,
        "verified_tool_capable": True,
        "verified_filesystem_edit": True,
        "sandbox_verified": True,
        "measured_latency": 44.26,
        "availability_status": "AVAILABLE",
        "cooldown_until": 0,
        "last_probe": time.time(),
        "failure_count": 0,
        "last_failure_type": None,
        "last_success": time.time(),
    },
    {
        "model_id": "free-coding",
        "provider": "omniroute",
        "free_only": True,
        "verified_tool_capable": True,
        "verified_filesystem_edit": True,
        "sandbox_verified": True,
        "measured_latency": 657.16,
        "availability_status": "AVAILABLE",
        "cooldown_until": 0,
        "last_probe": time.time(),
        "failure_count": 0,
        "last_failure_type": None,
        "last_success": time.time(),
    }
]

def load_registry():
    if not REGISTRY_PATH.exists():
        os.makedirs(REGISTRY_PATH.parent, exist_ok=True)
        with open(REGISTRY_PATH, "w") as f:
            json.dump(INITIAL_MODELS, f, indent=2)
        return INITIAL_MODELS
    
    try:
        with open(REGISTRY_PATH, "r") as f:
            data = json.load(f)
            return data
    except (json.JSONDecodeError, FileNotFoundError):
        return INITIAL_MODELS

def save_registry(data):
    os.makedirs(REGISTRY_PATH.parent, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(data, f, indent=2)

def get_eligible_models():
    data = load_registry()
    now = time.time()
    
    eligible = []
    for m in data:
        if not m.get("free_only"):
            continue
        if not m.get("verified_filesystem_edit"):
            continue
        if m.get("cooldown_until", 0) > now:
            continue
        if m.get("availability_status") == "DISABLED":
            continue
        
        eligible.append(m)
        
    return eligible

def record_failure(model_id, error_type):
    data = load_registry()
    now = time.time()
    
    for m in data:
        if m["model_id"] == model_id:
            m["failure_count"] = m.get("failure_count", 0) + 1
            m["last_failure_type"] = error_type
            m["last_probe"] = now
            
            error_lower = str(error_type).lower()
            if "429" in error_lower or "cooldown" in error_lower or "rate limit" in error_lower:
                m["cooldown_until"] = now + 300  # 5 minutes
                m["availability_status"] = "COOLDOWN"
            elif any(e in error_lower for e in ["timeout", "502", "503", "504", "5xx", "500"]):
                m["cooldown_until"] = now + 60   # 1 minute
                m["availability_status"] = "TIMEOUT"
            elif any(e in error_lower for e in ["402", "403", "404"]):
                m["cooldown_until"] = now + 3600 # 1 hour
                m["availability_status"] = "ERROR_4XX"
            else:
                m["cooldown_until"] = now + 30   # Default 30s
                m["availability_status"] = "ERROR"
            break
            
    save_registry(data)

def record_success(model_id):
    data = load_registry()
    now = time.time()
    
    for m in data:
        if m["model_id"] == model_id:
            m["failure_count"] = 0
            m["cooldown_until"] = 0
            m["availability_status"] = "AVAILABLE"
            m["last_success"] = now
            m["last_probe"] = now
            break
            
    save_registry(data)
