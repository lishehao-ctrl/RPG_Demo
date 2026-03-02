from __future__ import annotations

import re

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def test_request_id_generated_and_echoed(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None
    assert REQUEST_ID_PATTERN.fullmatch(request_id)


def test_request_id_passthrough_when_header_is_valid(client) -> None:
    inbound_id = "client.req-001_test"
    response = client.get("/health", headers={"X-Request-ID": inbound_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == inbound_id


def test_request_id_replaced_when_header_is_invalid(client) -> None:
    inbound_id = "bad request id with spaces"
    response = client.get("/health", headers={"X-Request-ID": inbound_id})
    assert response.status_code == 200
    returned = response.headers.get("X-Request-ID")
    assert returned is not None
    assert returned != inbound_id
    assert REQUEST_ID_PATTERN.fullmatch(returned)
