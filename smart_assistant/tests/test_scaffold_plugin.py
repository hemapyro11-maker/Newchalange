import json
import os
import py_compile
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

import scaffold_plugin as sp

requires_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="gcc not installed")
requires_node = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")


def test_scaffold_no_args_lists_types(make_ctx):
    result = sp._cmd_scaffold(make_ctx("scaffold", []))
    assert "web" in result and "android" in result and "ios" in result


def test_scaffold_unknown_type(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["bogus", "X", str(tmp_path)]))
    assert result.startswith("❌")


def test_scaffold_rejects_path_traversal_name(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["web", "../../evil", str(tmp_path)]))
    assert result.startswith("❌")


def test_scaffold_rejects_existing_nonempty_dir(make_ctx, tmp_path):
    project = tmp_path / "MyApp"
    project.mkdir()
    (project / "existing.txt").write_text("already here")
    result = sp._cmd_scaffold(make_ctx("scaffold", ["web", "MyApp", str(tmp_path)]))
    assert result.startswith("❌")


def test_scaffold_web_creates_valid_files(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["web", "MySite", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MySite"
    assert (root / "src" / "index.html").is_file()
    assert (root / "src" / "styles" / "main.css").is_file()
    assert (root / "src" / "scripts" / "main.js").is_file()
    assert (root / "package.json").is_file()
    assert (root / "eslint.config.js").is_file()
    assert "MySite" in (root / "src" / "index.html").read_text(encoding="utf-8")


def test_scaffold_android_produces_wellformed_manifest(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["android", "MyApp", str(tmp_path)]))
    assert result.startswith("✅")
    manifest = tmp_path / "MyApp" / "app" / "src" / "main" / "AndroidManifest.xml"
    ET.parse(manifest)  # raises if malformed


def test_scaffold_android_package_fallback_for_non_alnum_name(make_ctx, tmp_path):
    # regression: "!!!"  has zero alnum chars — package must fall back
    # to com.example.app, not the malformed "com.example."
    result = sp._cmd_scaffold(make_ctx("scaffold", ["android", "!!!", str(tmp_path)]))
    assert result.startswith("✅")
    manifest_kt_dir = tmp_path / "!!!" / "app" / "src" / "main" / "java" / "com" / "example" / "app"
    assert manifest_kt_dir.is_dir()
    build_gradle = (tmp_path / "!!!" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'namespace = "com.example.app"' in build_gradle
    assert 'namespace = "com.example."' not in build_gradle


def test_scaffold_ios_creates_swift_files(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["ios", "MyIOSApp", str(tmp_path)]))
    assert result.startswith("✅")
    assert (tmp_path / "MyIOSApp" / "MyIOSAppApp.swift").is_file()
    assert (tmp_path / "MyIOSApp" / "ContentView.swift").is_file()


def test_scaffold_python_creates_runnable_main(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["python", "MyScript", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyScript"
    py_compile.compile(str(root / "src" / "myscript" / "main.py"), doraise=True)
    assert (root / "pyproject.toml").is_file()
    proc = subprocess.run(
        ["python3", "-m", "myscript.main"], cwd=root / "src", capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "جاهز" in proc.stdout


def test_scaffold_game_creates_runnable_pygame_source(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["game", "MyGame", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyGame"
    py_compile.compile(str(root / "main.py"), doraise=True)
    py_compile.compile(str(root / "player.py"), doraise=True)
    assert "pygame" in (root / "requirements.txt").read_text(encoding="utf-8")
    assert (root / "tests" / "test_player.py").is_file()
    assert (root / "tests" / "test_headless_smoke.py").is_file()


requires_pygame = pytest.mark.skipif(
    subprocess.run(["python3", "-c", "import pygame"], capture_output=True).returncode != 0,
    reason="pygame not installed",
)


@requires_pygame
def test_scaffold_game_tests_actually_pass_headless(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["game", "MyGame", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyGame"
    env = {**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"}
    proc = subprocess.run(["python3", "-m", "pytest", "-q"], cwd=root, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "4 passed" in proc.stdout


def test_scaffold_backend_compiles(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["backend", "MyAPI", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyAPI"
    py_compile.compile(str(root / "app" / "main.py"), doraise=True)
    assert (root / "pyproject.toml").is_file()
    assert "fastapi" in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert (root / "Dockerfile").is_file()
    assert (root / "tests" / "test_health.py").is_file()


def test_scaffold_fullstack_creates_both_sides(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["fullstack", "MyFS", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyFS"
    assert (root / "frontend" / "src" / "index.html").is_file()
    assert (root / "backend" / "app" / "main.py").is_file()
    assert (root / "docker-compose.yml").is_file()
    py_compile.compile(str(root / "backend" / "app" / "main.py"), doraise=True)
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"backend", "frontend"}


def test_scaffold_docker_creates_valid_dockerfile(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["docker", "MyDock", str(tmp_path)]))
    assert result.startswith("✅")
    content = (tmp_path / "MyDock" / "Dockerfile").read_text(encoding="utf-8")
    # multi-stage build: builder stage + slim runtime stage
    assert content.count("FROM python") == 2
    assert "AS builder" in content
    # non-root user + healthcheck are required, not optional, for production images
    assert "USER appuser" in content
    assert "HEALTHCHECK" in content
    assert "CMD" in content
    dockerignore = (tmp_path / "MyDock" / ".dockerignore").read_text(encoding="utf-8")
    assert ".git" in dockerignore and "__pycache__" in dockerignore


def test_scaffold_ci_produces_valid_yaml(make_ctx, tmp_path):
    yaml = pytest.importorskip("yaml")
    result = sp._cmd_scaffold(make_ctx("scaffold", ["ci", "MyCI", str(tmp_path)]))
    assert result.startswith("✅")
    workflow = tmp_path / "MyCI" / ".github" / "workflows" / "ci.yml"
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    jobs = data["jobs"]
    assert set(jobs) == {"lint", "test", "build"}
    assert jobs["test"]["needs"] == "lint"
    assert jobs["build"]["needs"] == "test"
    assert "matrix" in jobs["test"]["strategy"]


def test_scaffold_pytest_is_runnable(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["pytest", "MyTests", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyTests"
    proc = subprocess.run(["python3", "-m", "pytest", "-q", str(root)], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "3 passed" in proc.stdout
    assert (root / "tox.ini").is_file()
    assert (root / "requirements-dev.txt").is_file()


def test_scaffold_ml_script_compiles(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["ml", "MyML", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyML"
    for mod in ("data", "model", "train", "evaluate", "__main__"):
        py_compile.compile(str(root / "src" / "myml" / f"{mod}.py"), doraise=True)
    assert "scikit-learn" in (root / "pyproject.toml").read_text(encoding="utf-8")


@pytest.mark.skipif(
    subprocess.run(["python3", "-c", "import sklearn"], capture_output=True).returncode != 0,
    reason="scikit-learn not installed",
)
def test_scaffold_ml_script_actually_trains(make_ctx, tmp_path):
    sp._cmd_scaffold(make_ctx("scaffold", ["ml", "MyML", str(tmp_path)]))
    root = tmp_path / "MyML"
    proc = subprocess.run(
        ["python3", "-m", "myml"], cwd=root / "src", capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "accuracy:" in proc.stdout


def test_scaffold_quantum_script_compiles(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["quantum", "MyQ", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyQ"
    py_compile.compile(str(root / "bell_state.py"), doraise=True)
    py_compile.compile(str(root / "circuit.py"), doraise=True)
    assert (root / "tests" / "test_circuit.py").is_file()
    assert (root / "tests" / "test_bell_state_simulation.py").is_file()


requires_qiskit_aer = pytest.mark.skipif(
    subprocess.run(["python3", "-c", "import qiskit_aer"], capture_output=True).returncode != 0,
    reason="qiskit-aer not installed",
)


@requires_qiskit_aer
def test_scaffold_quantum_tests_actually_pass(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["quantum", "MyQ", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyQ"
    proc = subprocess.run(["python3", "-m", "pytest", "-q"], cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "3 passed" in proc.stdout


@requires_qiskit_aer
def test_scaffold_quantum_bell_state_runs_and_shows_entanglement(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["quantum", "MyQ", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyQ"
    proc = subprocess.run(["python3", "bell_state.py"], cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    # الـ dict بيتطبع بمفاتيح متعلّمة بـ quotes زي {'11': 499, '00': 501} —
    # بندوّر على المفاتيح المقتبسة بالظبط عشان مانتلخبطش مع أرقام الـ counts
    # نفسها (501 مثلاً بيحتوي على substring "01").
    assert "'00'" in proc.stdout or "'11'" in proc.stdout
    assert "'01'" not in proc.stdout and "'10'" not in proc.stdout


def test_scaffold_blockchain_valid_solidity_and_json(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["blockchain", "MyToken", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyToken"
    sol = (root / "contracts" / "MyToken.sol").read_text(encoding="utf-8")
    assert "pragma solidity" in sol
    assert "contract MyToken" in sol
    data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    assert "hardhat" in data["devDependencies"]
    assert "@nomicfoundation/hardhat-toolbox" in data["devDependencies"]
    assert data["scripts"]["test"] == "hardhat test"
    assert (root / "hardhat.config.js").is_file()
    assert (root / "test" / "MyToken.test.js").is_file()
    assert (root / ".gitignore").is_file()
    assert "node_modules/" in (root / ".gitignore").read_text(encoding="utf-8")


def test_scaffold_blockchain_sanitizes_contract_name(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["blockchain", "!!!", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "!!!"
    assert (root / "contracts" / "MyContract.sol").is_file()
    assert (root / "test" / "MyContract.test.js").is_file()


@requires_node
def test_scaffold_blockchain_config_and_test_are_valid_js(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["blockchain", "MyToken", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyToken"
    for f in ("hardhat.config.js", "test/MyToken.test.js"):
        proc = subprocess.run(["node", "--check", str(root / f)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr


def test_scaffold_blockchain_test_file_exercises_every_public_function(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["blockchain", "MyToken", str(tmp_path)]))
    assert result.startswith("✅")
    test_js = (tmp_path / "MyToken" / "test" / "MyToken.test.js").read_text(encoding="utf-8")
    assert "getContractFactory(\"MyToken\")" in test_js
    assert ".message()" in test_js
    assert ".setMessage(" in test_js
    assert "revertedWith" in test_js  # exercises the owner-only guard


@requires_gcc
def test_scaffold_embedded_c_compiles(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["embedded", "MyMCU", str(tmp_path)]))
    assert result.startswith("✅")
    proc = subprocess.run(
        ["gcc", "-c", "-ffreestanding", "-std=c11", str(tmp_path / "MyMCU" / "main.c"), "-o", "/dev/null"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


@requires_gcc
def test_scaffold_embedded_blink_logic_actually_runs_and_passes(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["embedded", "MyMCU", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyMCU"
    proc = subprocess.run(["make", "test"], cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "blink logic ok" in proc.stdout


def test_scaffold_kernel_module_has_real_tabs_in_makefile(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["kernel_module", "MyMod", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyMod"
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    assert "\n\tmake -C" in makefile  # recipe lines need literal tabs, not spaces
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "*.ko" in gitignore and "Module.symvers" in gitignore
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "insmod" in readme and "rmmod" in readme and "dmesg" in readme


def test_scaffold_multiplayer_server_compiles(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["multiplayer_server", "MyMP", str(tmp_path)]))
    assert result.startswith("✅")
    py_compile.compile(str(tmp_path / "MyMP" / "server.py"), doraise=True)
    py_compile.compile(str(tmp_path / "MyMP" / "client.py"), doraise=True)


def test_scaffold_multiplayer_server_actually_accepts_connections(make_ctx, tmp_path):
    import socket
    import time

    sp._cmd_scaffold(make_ctx("scaffold", ["multiplayer_server", "MyMP", str(tmp_path)]))
    root = tmp_path / "MyMP"
    proc = subprocess.Popen(
        ["python3", "server.py"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        for _ in range(30):
            time.sleep(0.1)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex(("127.0.0.1", 8765)) == 0:
                    break
        else:
            pytest.fail("server never opened its port")
        client = subprocess.run(["python3", "client.py"], cwd=root, capture_output=True, text=True, timeout=5)
        assert client.returncode == 0
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_scaffold_arvr_references_aframe(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["arvr", "MyVR", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MyVR"
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "a-scene" in html
    assert "aframe" in html.lower()
    assert "src/main.js" in html
    data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    assert data["scripts"]["start"].startswith("http-server")


@requires_node
def test_scaffold_arvr_main_js_is_valid_and_registers_component(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["arvr", "MyVR", str(tmp_path)]))
    assert result.startswith("✅")
    main_js = tmp_path / "MyVR" / "src" / "main.js"
    proc = subprocess.run(["node", "--check", str(main_js)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "AFRAME.registerComponent" in main_js.read_text(encoding="utf-8")


def test_scaffold_screenplay_valid_fountain(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["screenplay", "MyScript", str(tmp_path)]))
    assert result.startswith("✅")
    content = (tmp_path / "MyScript" / "MyScript.fountain").read_text(encoding="utf-8")
    assert "INT." in content
    assert "FADE IN:" in content


def test_scaffold_ink_story_has_valid_structure(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["ink_story", "MyStory", str(tmp_path)]))
    assert result.startswith("✅")
    content = (tmp_path / "MyStory" / "story.ink").read_text(encoding="utf-8")
    assert "-> start" in content
    assert "=== start ===" in content
    assert "-> END" in content
