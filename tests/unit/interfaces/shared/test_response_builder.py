"""Unit tests for the shared response builder."""

from __future__ import annotations

import json
from datetime import datetime

from interfaces.shared.response_builder import (
    error_response,
    no_content_response,
    success_response,
)


class TestSuccessResponse:
    """Tests for success_response."""

    def test_returns_correct_status_code(self) -> None:
        result = success_response(200, {"key": "value"})
        assert result["statusCode"] == 200

    def test_returns_201_for_creation(self) -> None:
        result = success_response(201, {"id": "abc"})
        assert result["statusCode"] == 201

    def test_body_is_json_serialized(self) -> None:
        data = {"name": "test", "count": 42}
        result = success_response(200, data)
        assert json.loads(result["body"]) == data

    def test_includes_cors_headers(self) -> None:
        result = success_response(200, {})
        headers = result["headers"]
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert headers["Access-Control-Allow-Headers"] == "Content-Type,Authorization"
        assert headers["Access-Control-Allow-Methods"] == "*"
        assert headers["Content-Type"] == "application/json"

    def test_serializes_datetime_with_default_str(self) -> None:
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = success_response(200, {"created_at": dt})
        body = json.loads(result["body"])
        assert body["created_at"] == str(dt)

    def test_serializes_list_data(self) -> None:
        data = [{"id": "1"}, {"id": "2"}]
        result = success_response(200, data)
        assert json.loads(result["body"]) == data


class TestErrorResponse:
    """Tests for error_response."""

    def test_returns_correct_status_code(self) -> None:
        result = error_response(400, "Bad request")
        assert result["statusCode"] == 400

    def test_body_contains_error_field(self) -> None:
        result = error_response(404, "Not found")
        body = json.loads(result["body"])
        assert body == {"error": "Not found"}

    def test_includes_cors_headers(self) -> None:
        result = error_response(500, "Internal server error")
        headers = result["headers"]
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert headers["Access-Control-Allow-Headers"] == "Content-Type,Authorization"
        assert headers["Access-Control-Allow-Methods"] == "*"
        assert headers["Content-Type"] == "application/json"

    def test_various_status_codes(self) -> None:
        for code in (400, 401, 403, 404, 409, 500):
            result = error_response(code, "msg")
            assert result["statusCode"] == code


class TestNoContentResponse:
    """Tests for no_content_response."""

    def test_returns_204_status(self) -> None:
        result = no_content_response()
        assert result["statusCode"] == 204

    def test_body_is_empty_string(self) -> None:
        result = no_content_response()
        assert result["body"] == ""

    def test_includes_cors_headers(self) -> None:
        result = no_content_response()
        headers = result["headers"]
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert headers["Access-Control-Allow-Headers"] == "Content-Type,Authorization"
        assert headers["Access-Control-Allow-Methods"] == "*"
