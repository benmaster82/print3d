import json
import subprocess
import anyio
import pytest
from mcp import Client

from print3d import doctor
from print3d.blender import BlenderError
from print3d.studio import StudioError


@pytest.fixture
def probes(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "find_blender", lambda: tmp_path / "blender")
    monkeypatch.setattr(doctor, "find_studio", lambda: tmp_path / "studio")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        text = "Blender 4.2.9\n" if command[-1] == "--version" else "BambuStudio 2.8.2.61\n"
        return subprocess.CompletedProcess(command, 0, text, "")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    return calls


def test_reports_paths_versions_and_bounded_probes_without_creating_jobs(probes, tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT3D_JOBS", str(tmp_path / "jobs"))
    result = doctor.dependency_status()
    assert result["ready"]
    assert result["dependencies"]["blender"]["version"] == "4.2.9"
    assert result["dependencies"]["studio"]["version"] == "2.8.2.61"
    assert all(options["timeout"] == doctor.PROBE_TIMEOUT for _, options in probes)
    assert not (tmp_path / "jobs").exists()


def test_missing_dependencies_are_reported_together(probes, monkeypatch):
    def absent_blender():
        raise BlenderError("Set BLENDER_BIN")

    def absent_studio():
        raise StudioError("Set BAMBU_STUDIO_BIN")

    monkeypatch.setattr(doctor, "find_blender", absent_blender)
    monkeypatch.setattr(doctor, "find_studio", absent_studio)
    report = doctor.dependency_status()
    assert not report["ready"]
    assert all(check["status"] == "missing" for check in report["dependencies"].values())
    assert "BAMBU_STUDIO_BIN" in report["dependencies"]["studio"]["message"]
    assert probes == []


@pytest.mark.parametrize("failure", ["timeout", "launch", "exit"])
def test_unavailable_probe_does_not_hide_other_dependency(probes, monkeypatch, failure):
    run = doctor.subprocess.run

    def broken(command, **kwargs):
        if command[-1] == "--version":
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, doctor.PROBE_TIMEOUT)
            if failure == "launch":
                raise PermissionError("Cannot execute")
            return subprocess.CompletedProcess(command, 1, "", "error")
        return run(command, **kwargs)

    monkeypatch.setattr(doctor.subprocess, "run", broken)
    report = doctor.dependency_status()
    assert not report["ready"]
    assert report["dependencies"]["blender"]["status"] == "unavailable"
    assert report["dependencies"]["studio"]["ready"]


def test_unknown_version_is_not_a_missing_dependency(probes, monkeypatch):
    monkeypatch.setattr(doctor.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 0, "", ""))
    report = doctor.dependency_status()
    assert report["ready"]
    assert all(check["version"] is None for check in report["dependencies"].values())


@pytest.mark.parametrize("ready", [True, False])
def test_cli_exit_code_matches_readiness(monkeypatch, capsys, ready):
    from print3d import cli
    monkeypatch.setattr(cli, "dependency_status", lambda: {"ready": ready})
    assert cli.main(["doctor"]) == (0 if ready else 1)
    assert json.loads(capsys.readouterr().out) == {"ready": ready}


def test_mcp_doctor_is_read_only_and_reports_missing_dependency(probes, monkeypatch):
    from print3d.mcp_server import server
    monkeypatch.setattr(doctor.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 1, "", ""))

    async def run():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            tool = next(tool for tool in tools if tool.name == "doctor")
            assert tool.annotations.read_only_hint
            response = await client.call_tool("doctor", {})
            assert not response.is_error
            assert not json.loads(response.content[0].text)["ready"]

    anyio.run(run)
