import os
import subprocess
from pathlib import Path
import yaml

def get_agent_config():
    config_path = Path("config/agent.yaml")
    if config_path.exists():
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    return {"test_timeout_seconds": 60}

def get_safe_env():
    # Only pass safe environment variables
    safe_keys = {"PATH", "LANG", "LC_ALL", "USER", "HOME"}
    env = {k: v for k, v in os.environ.items() if k in safe_keys}
    return env

def run_in_sandbox(command_list, cwd):
    config = get_agent_config()
    timeout = config.get("test_timeout_seconds", 60)
    
    print(f"Running safe command: {' '.join(command_list)} in {cwd}")
    try:
        result = subprocess.run(
            command_list,
            cwd=str(cwd),
            env=get_safe_env(),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Command timed out",
            "returncode": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -2
        }

def discover_and_run_tests(cwd):
    cwd_path = Path(cwd)
    results = []
    
    # Python
    if (cwd_path / "pytest.ini").exists() or (cwd_path / "setup.cfg").exists() or (cwd_path / "pyproject.toml").exists():
        # Check if pytest is available
        if (cwd_path / "tests").exists():
            res = run_in_sandbox(["pytest", "tests/"], cwd)
            results.append({"framework": "pytest", "result": res})
            
    # JavaScript/TypeScript
    if (cwd_path / "package.json").exists():
        res = run_in_sandbox(["npm", "test"], cwd)
        results.append({"framework": "npm", "result": res})
        
    # Rust
    if (cwd_path / "Cargo.toml").exists():
        res = run_in_sandbox(["cargo", "test"], cwd)
        results.append({"framework": "cargo", "result": res})
        
    # Java (Maven)
    if (cwd_path / "pom.xml").exists():
        res = run_in_sandbox(["mvn", "test"], cwd)
        results.append({"framework": "maven", "result": res})
        
    # Java (Gradle)
    if (cwd_path / "build.gradle").exists() or (cwd_path / "build.gradle.kts").exists():
        res = run_in_sandbox(["./gradlew", "test"], cwd)
        results.append({"framework": "gradle", "result": res})
        
    # Go
    if (cwd_path / "go.mod").exists():
        res_test = run_in_sandbox(["go", "test", "./..."], cwd)
        results.append({"framework": "go test", "result": res_test})
        res_vet = run_in_sandbox(["go", "vet", "./..."], cwd)
        results.append({"framework": "go vet", "result": res_vet})
        
    return results
