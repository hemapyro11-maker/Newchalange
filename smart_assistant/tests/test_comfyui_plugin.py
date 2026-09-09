import json

from plugins import comfyui_plugin as cp


def test_url_policy_allows_local_http_and_remote_https():
    assert cp._valid_url("http://127.0.0.1:8188")
    assert cp._valid_url("http://localhost:9000")
    assert cp._valid_url("https://comfy.example.com")
    assert not cp._valid_url("http://comfy.example.com")
    assert not cp._valid_url("file:///tmp/x")


def test_queue_submits_api_workflow(tmp_path, make_ctx, monkeypatch):
    workflow = tmp_path / "workflow.json"
    workflow.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {}}}), encoding="utf-8")
    seen = {}

    def fake_request(path, payload=None, timeout=20):
        seen.update(path=path, payload=payload, timeout=timeout)
        return {"prompt_id": "job-123"}

    monkeypatch.setattr(cp, "_request", fake_request)
    result = cp._cmd_queue(make_ctx(f'comfy_queue "{workflow}"', [str(workflow)]))
    assert "job-123" in result
    assert seen["path"] == "/prompt"
    assert seen["payload"]["prompt"]["1"]["class_type"] == "KSampler"


def test_queue_rejects_invalid_json(tmp_path, make_ctx):
    workflow = tmp_path / "workflow.json"
    workflow.write_text("[]", encoding="utf-8")
    assert "non-empty object" in cp._cmd_queue(make_ctx("comfy_queue", [str(workflow)]))
