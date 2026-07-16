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
        body=json.dumps({"clientId": "A", "terminals": ["1"], "intervalMinutes": 5}),
    )

    # Then
    assert response.code == 200
    payload = json.loads(response.body)
    assert payload == {"status": "ok"}


async def test_active_terminals_rejects_non_list(jp_fetch):
    """DEF-14: a string 'terminals' must not be iterated into bogus names."""
    import tornado.httpclient
    import pytest

    with pytest.raises(tornado.httpclient.HTTPClientError) as exc_info:
        await jp_fetch(
            NAMESPACE,
            "active-terminals",
            method="POST",
            body=json.dumps({"clientId": "A", "terminals": "12"}),
        )
    assert exc_info.value.code == 400


async def test_non_object_bodies_rejected(jp_fetch):
    """DEF-14 hardening: JSON-valid non-object bodies are 400, not 500."""
    import tornado.httpclient
    import pytest

    for endpoint, body in (
        ("settings", "5"),
        ("active-terminals", "[]"),
        ("cull-workspaces", '"x"'),
    ):
        with pytest.raises(tornado.httpclient.HTTPClientError) as exc_info:
            await jp_fetch(NAMESPACE, endpoint, method="POST", body=body)
        assert exc_info.value.code == 400, endpoint


async def test_invalid_utf8_body_rejected(jp_fetch):
    """Invalid UTF-8 raises UnicodeDecodeError, not JSONDecodeError - still 400."""
    import tornado.httpclient
    import pytest

    for endpoint in ("settings", "active-terminals", "cull-workspaces"):
        with pytest.raises(tornado.httpclient.HTTPClientError) as exc_info:
            await jp_fetch(NAMESPACE, endpoint, method="POST", body=b"{\xff}")
        assert exc_info.value.code == 400, endpoint


async def test_deeply_nested_body_rejected(jp_fetch):
    """json.loads raises RecursionError on pathological nesting - still 400."""
    import tornado.httpclient
    import pytest

    with pytest.raises(tornado.httpclient.HTTPClientError) as exc_info:
        await jp_fetch(NAMESPACE, "settings", method="POST", body="[" * 200000)
    assert exc_info.value.code == 400


async def test_cull_workspaces_rejects_bool_timeout(jp_fetch):
    """DEF-14 hardening: {"timeout": true} must not become a 60s threshold."""
    import tornado.httpclient
    import pytest

    with pytest.raises(tornado.httpclient.HTTPClientError) as exc_info:
        await jp_fetch(
            NAMESPACE,
            "cull-workspaces",
            method="POST",
            body=json.dumps({"timeout": True}),
        )
    assert exc_info.value.code == 400


async def test_settings_rejects_bad_type(jp_fetch):
    """DEF-14: a type-invalid settings payload returns 400 and applies nothing."""
    import tornado.httpclient
    import pytest

    with pytest.raises(tornado.httpclient.HTTPClientError) as exc_info:
        await jp_fetch(
            NAMESPACE,
            "settings",
            method="POST",
            body=json.dumps({"kernelCullEnabled": False, "kernelCullIdleTimeout": "abc"}),
        )
    assert exc_info.value.code == 400

    status = await jp_fetch(NAMESPACE, "status")
    settings = json.loads(status.body)["settings"]
    assert settings["kernelCullEnabled"] is True
    assert settings["kernelCullIdleTimeout"] == 60
