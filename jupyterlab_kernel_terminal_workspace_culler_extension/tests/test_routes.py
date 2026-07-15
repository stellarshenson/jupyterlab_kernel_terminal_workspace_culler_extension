"""Integration tests for the resource culler route handlers."""

import json

NAMESPACE = "jupyterlab-kernel-terminal-workspace-culler-extension"


async def test_status_endpoint(jp_fetch):
    # When
    response = await jp_fetch(NAMESPACE, "status")

    # Then
    assert response.code == 200
    payload = json.loads(response.body)
    assert "settings" in payload
    assert "running" in payload
    assert payload["settings"]["kernelCullEnabled"] is True


async def test_cull_result_endpoint(jp_fetch):
    # When
    response = await jp_fetch(NAMESPACE, "cull-result")

    # Then
    assert response.code == 200
    payload = json.loads(response.body)
    assert payload == {
        "kernels_culled": [],
        "terminals_culled": [],
        "workspaces_culled": [],
    }


async def test_active_terminals_endpoint(jp_fetch):
    # When
    response = await jp_fetch(
        NAMESPACE,
        "active-terminals",
        method="POST",
        body=json.dumps({"clientId": "A", "terminals": ["1"]}),
    )

    # Then
    assert response.code == 200
    payload = json.loads(response.body)
    assert payload == {"status": "ok"}
