"""Tests for workspace resource manager API."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_agent.app.runner.workspace_api import router


@pytest.fixture
def app(tmp_path):
    """Create a test FastAPI app with workspace router."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def workspace_dir(tmp_path):
    """Create a test workspace directory with sample files."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "file_a.txt").write_text("hello world")
    (ws / "file_b.py").write_text("print('test')")
    (ws / "subdir").mkdir()
    (ws / "subdir" / "nested.txt").write_text("nested content")
    return ws


@pytest.fixture
def workspace_id(client, workspace_dir, monkeypatch, tmp_path):
    """Create a test workspace and return its ID."""
    # Patch the store path to use temp dir
    store_path = tmp_path / "store" / "workspaces.json"
    monkeypatch.setattr(
        "open_agent.app.runner.workspace_api._workspace_store_path",
        lambda: store_path,
    )
    resp = client.post(
        "/api/workspace/",
        json={"name": "test", "path": str(workspace_dir)},
    )
    assert resp.status_code == 200
    return resp.json()["workspace"]["id"]


class TestWorkspaceCRUD:
    def test_list_empty(self, client, monkeypatch, tmp_path):
        store_path = tmp_path / "store" / "workspaces.json"
        monkeypatch.setattr(
            "open_agent.app.runner.workspace_api._workspace_store_path",
            lambda: store_path,
        )
        resp = client.get("/api/workspace/")
        assert resp.status_code == 200
        assert resp.json()["workspaces"] == []

    def test_create_workspace(self, client, monkeypatch, tmp_path):
        store_path = tmp_path / "store" / "workspaces.json"
        ws_dir = tmp_path / "myws"
        monkeypatch.setattr(
            "open_agent.app.runner.workspace_api._workspace_store_path",
            lambda: store_path,
        )
        resp = client.post(
            "/api/workspace/",
            json={"name": "My Workspace", "path": str(ws_dir)},
        )
        assert resp.status_code == 200
        ws = resp.json()["workspace"]
        assert ws["name"] == "My Workspace"
        assert ws["id"].startswith("ws_")
        assert ws_dir.exists()

    def test_delete_workspace(self, client, workspace_id):
        resp = client.delete(f"/api/workspace/{workspace_id}")
        assert resp.status_code == 200

    def test_delete_nonexistent(self, client):
        resp = client.delete("/api/workspace/ws_nonexistent")
        assert resp.status_code == 404

    def test_update_workspace(self, client, workspace_id):
        resp = client.put(
            f"/api/workspace/{workspace_id}",
            json={"name": "Renamed"},
        )
        assert resp.status_code == 200
        assert resp.json()["workspace"]["name"] == "Renamed"


class TestFileOperations:
    def test_list_files(self, client, workspace_id):
        resp = client.get(f"/api/workspace/{workspace_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        names = [f["name"] for f in data["files"]]
        assert "file_a.txt" in names
        assert "subdir" in names

    def test_list_subdir(self, client, workspace_id):
        resp = client.get(f"/api/workspace/{workspace_id}/files?path=subdir")
        assert resp.status_code == 200
        names = [f["name"] for f in resp.json()["files"]]
        assert "nested.txt" in names

    def test_read_file(self, client, workspace_id):
        resp = client.get(f"/api/workspace/{workspace_id}/read?path=file_a.txt")
        assert resp.status_code == 200
        assert "hello world" in resp.json()["content"]

    def test_read_with_offset_limit(self, client, workspace_id):
        resp = client.get(
            f"/api/workspace/{workspace_id}/read?path=file_b.py&offset=1&limit=1"
        )
        assert resp.status_code == 200
        content = resp.json()["content"]
        assert "1:" in content

    def test_read_nonexistent(self, client, workspace_id):
        resp = client.get(f"/api/workspace/{workspace_id}/read?path=nope.txt")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self, client, workspace_id):
        resp = client.get(
            f"/api/workspace/{workspace_id}/read?path=../../../etc/passwd"
        )
        assert resp.status_code == 403

    def test_write_file(self, client, workspace_id):
        resp = client.post(
            f"/api/workspace/{workspace_id}/write",
            json={"path": "new_file.txt", "content": "new content"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"]

    def test_mkdir(self, client, workspace_id):
        resp = client.post(
            f"/api/workspace/{workspace_id}/mkdir",
            json={"path": "new_dir"},
        )
        assert resp.status_code == 200

    def test_rename(self, client, workspace_id):
        resp = client.post(
            f"/api/workspace/{workspace_id}/rename",
            json={"path": "file_a.txt", "name": "renamed.txt"},
        )
        assert resp.status_code == 200
        assert resp.json()["new_path"] == "renamed.txt"

    def test_rename_rejects_path_traversal_name(self, client, workspace_id, workspace_dir):
        resp = client.post(
            f"/api/workspace/{workspace_id}/rename",
            json={"path": "file_a.txt", "name": "../escaped.txt"},
        )
        assert resp.status_code == 400
        assert (workspace_dir.parent / "escaped.txt").exists() is False
        assert (workspace_dir / "file_a.txt").exists()

    def test_upload_rejects_path_traversal_filename(self, client, workspace_id, workspace_dir):
        resp = client.post(
            f"/api/workspace/{workspace_id}/upload",
            files={"file": ("../escaped_upload.txt", b"bad")},
        )
        assert resp.status_code == 400
        assert (workspace_dir.parent / "escaped_upload.txt").exists() is False

    def test_delete_file(self, client, workspace_id):
        resp = client.post(
            f"/api/workspace/{workspace_id}/delete",
            json={"path": "file_b.py"},
        )
        assert resp.status_code == 200


class TestSearch:
    def test_glob(self, client, workspace_id):
        resp = client.post(
            f"/api/workspace/{workspace_id}/glob",
            json={"pattern": "**/*.py"},
        )
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert "file_b.py" in files

    def test_search_content(self, client, workspace_id):
        resp = client.post(
            f"/api/workspace/{workspace_id}/search",
            json={"pattern": "hello"},
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        assert results[0]["file"] == "file_a.txt"

    def test_search_no_match(self, client, workspace_id):
        resp = client.post(
            f"/api/workspace/{workspace_id}/search",
            json={"pattern": "zzzznonexistent"},
        )
        assert resp.status_code == 200
        assert resp.json()["results"] == []
