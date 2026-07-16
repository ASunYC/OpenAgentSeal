from pathlib import Path
import subprocess
import sys
import tomllib

import desktop.backend.open_agent_backend as backend_entry


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_cli_entrypoint_runs_without_desktop_backend_defaults():
    entrypoint = ROOT / "scripts" / "packaging" / "open_agent_cli.py"

    result = subprocess.run(
        [sys.executable, str(entrypoint), "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("open-agent ")


def test_cli_does_not_load_the_legacy_python_tray():
    cli_source = (ROOT / "open_agent" / "cli.py").read_text(encoding="utf-8")
    launcher_source = (ROOT / "run.py").read_text(encoding="utf-8")
    dependencies = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["dependencies"]

    assert "from open_agent.tray import" not in cli_source
    assert "from open_agent.tray import" not in launcher_source
    assert 'command == "/tray"' not in cli_source
    assert "run.py --tray" not in cli_source
    assert '"--tray"' not in launcher_source
    assert not (ROOT / "open_agent" / "tray.py").exists()
    assert not any(dependency.startswith("pystray") for dependency in dependencies)


def test_cross_platform_packaging_replaces_legacy_powershell_pipeline():
    assert not (ROOT / "scripts" / "build_desktop_sidecar.ps1").exists()
    assert not (ROOT / "scripts" / "sync_version.ps1").exists()
    assert (ROOT / "scripts" / "package-release.mjs").is_file()
    assert (ROOT / "scripts" / "sync-version.mjs").is_file()


def test_desktop_backend_uses_xdg_state_directory_on_linux(monkeypatch, tmp_path):
    for variable in ("LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    assert backend_entry._desktop_log_path(platform_name="posix") == (
        tmp_path / "OpenAgentSeal" / "desktop-backend.log"
    )
