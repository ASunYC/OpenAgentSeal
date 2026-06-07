import json
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from open_agent.plugins.builtin.mineru_service import (
    MinerUService,
    MinerUResult,
    add_result_to_library,
    split_markdown_for_translation,
)


def test_split_markdown_preserves_protected_segments():
    source = """# Paper

Text before formula $E = mc^2$.

![figure](images/figure.png)

```python
print("do not translate")
```
"""

    chunks, placeholders = split_markdown_for_translation(source, limit=50)
    joined = "".join(chunks)

    assert len(chunks) > 1
    assert "$E = mc^2$" in placeholders.values()
    assert "![figure](images/figure.png)" in placeholders.values()
    assert any('print("do not translate")' in value for value in placeholders.values())
    assert "@@MINERU_KEEP_" in joined


def test_add_result_to_library_adds_and_selects_result_directory(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    result_dir = data_dir / "plugins" / "mineru" / "results" / "job"
    result_dir.mkdir(parents=True)
    (result_dir / "original.md").write_text("# Original", encoding="utf-8")
    (result_dir / "translated_zh.md").write_text("# Translated", encoding="utf-8")
    monkeypatch.setattr(
        "open_agent.plugins.builtin.mineru_service.get_data_dir",
        lambda: data_dir,
    )

    add_result_to_library(result_dir)
    state = json.loads((data_dir / "workspace_sources.json").read_text(encoding="utf-8"))

    assert state["sources"][0]["path"] == str(result_dir)
    assert state["selected_paths"] == [str(result_dir)]


@pytest.mark.asyncio
async def test_mineru_result_serializes_expected_outputs(tmp_path):
    result_dir = tmp_path / "job"
    result_dir.mkdir()
    markdown = result_dir / "original.md"
    markdown.write_text("# Parsed", encoding="utf-8")
    result = MinerUResult(
        task_id="task-1",
        protocol="self-hosted",
        result_dir=result_dir,
        markdown_path=markdown,
    )

    payload = result.to_dict()

    assert payload["task_id"] == "task-1"
    assert payload["protocol"] == "self-hosted"
    assert payload["markdown_path"] == str(markdown)


@pytest.mark.asyncio
async def test_self_hosted_mineru_api_is_parsed_with_one_connection_config(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-test")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "open_agent.plugins.builtin.mineru_service.get_data_dir",
        lambda: data_dir,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/tasks":
            return httpx.Response(200, json={"task_id": "local-1"})
        if request.url.path == "/tasks/local-1":
            return httpx.Response(200, json={"state": "done"})
        if request.url.path == "/tasks/local-1/result":
            return httpx.Response(
                200,
                json={"result": {"paper.pdf": {"md_content": "# Parsed"}}},
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://mineru.local",
    ) as client:
        result = await MinerUService(
            "http://mineru.local",
            client=client,
        ).parse_document(source, add_to_library=False)

    assert result.protocol == "self-hosted"
    assert result.markdown_path.read_text(encoding="utf-8") == "# Parsed"


@pytest.mark.asyncio
async def test_official_mineru_api_downloads_zip_result(tmp_path, monkeypatch):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-test")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "open_agent.plugins.builtin.mineru_service.get_data_dir",
        lambda: data_dir,
    )
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("paper/full.md", "# Cloud parsed")
        archive.writestr("paper/images/chart.png", b"image")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v4/file-urls/batch":
            assert request.headers["Authorization"] == "Bearer token"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "file_urls": ["https://upload.test/paper"],
                    },
                },
            )
        if request.url.host == "upload.test":
            return httpx.Response(200)
        if request.url.path == "/api/v4/extract-results/batch/batch-1":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "state": "done",
                                "full_zip_url": "https://download.test/result.zip",
                            }
                        ]
                    },
                },
            )
        if request.url.host == "download.test":
            return httpx.Response(
                200,
                content=zip_buffer.getvalue(),
                headers={"content-type": "application/zip"},
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mineru.net",
    ) as client:
        result = await MinerUService(
            "https://mineru.net",
            api_token="token",
            client=client,
        ).parse_document(source, add_to_library=False)

    assert result.protocol == "cloud-v4"
    assert result.markdown_path.read_text(encoding="utf-8") == "# Cloud parsed"
    assert (result.result_dir / "images" / "chart.png").exists()
