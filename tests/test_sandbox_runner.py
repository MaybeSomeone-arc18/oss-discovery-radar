
def test_sandbox_runner_detects_mvnw(tmp_path):
    from src.sandbox_runner import discover_and_run_tests
    import os
    (tmp_path / "pom.xml").touch()
    (tmp_path / "mvnw").touch()

    import subprocess
    def fake_run(args, *a, **kw):
        return {"success": True, "stdout": f"ran {' '.join(args)}", "stderr": "", "returncode": 0}

    import src.sandbox_runner
    original_run = src.sandbox_runner.run_in_sandbox
    src.sandbox_runner.run_in_sandbox = fake_run
    try:
        results = discover_and_run_tests(str(tmp_path))
        assert any(r["framework"] == "maven" and "ran ./mvnw test" in r["result"]["stdout"] for r in results)
    finally:
        src.sandbox_runner.run_in_sandbox = original_run

def test_sandbox_runner_falls_back_to_mvn(tmp_path):
    from src.sandbox_runner import discover_and_run_tests
    import os
    (tmp_path / "pom.xml").touch()

    import subprocess
    def fake_run(args, *a, **kw):
        return {"success": True, "stdout": f"ran {' '.join(args)}", "stderr": "", "returncode": 0}

    import src.sandbox_runner
    original_run = src.sandbox_runner.run_in_sandbox
    src.sandbox_runner.run_in_sandbox = fake_run
    try:
        results = discover_and_run_tests(str(tmp_path))
        assert any(r["framework"] == "maven" and "ran mvn test" in r["result"]["stdout"] for r in results)
    finally:
        src.sandbox_runner.run_in_sandbox = original_run
