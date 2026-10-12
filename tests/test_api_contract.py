"""OpenAPI contract: every public route documents its response and errors."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from nba_insights.api import app, schemas

NON_JSON = {
    ("get", "/players/{player_id}/headshot"),
    ("get", "/players/{player_id}/card"),
    ("get", "/posters/compare"),
    ("get", "/posters/game"),
}


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def _operations(spec: dict):
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            yield method, path, operation


def test_json_routes_declare_a_response_schema(spec):
    missing = [
        (method, path)
        for method, path, operation in _operations(spec)
        if (method, path) not in NON_JSON
        and not operation["responses"]["200"]
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    ]
    assert missing == []


def test_every_route_belongs_to_a_domain_tag(spec):
    declared = {tag["name"] for tag in spec["tags"]}
    for method, path, operation in _operations(spec):
        assert operation.get("tags"), (method, path)
        assert set(operation["tags"]) <= declared, (method, path)


@pytest.mark.parametrize(
    ("method", "path", "codes"),
    [
        ("get", "/players/{player_id}", {"404"}),
        ("get", "/teams/{team}/profile", {"404", "503"}),
        ("get", "/predict/game", {"404", "422", "503"}),
        ("get", "/predict/simulate", {"401", "403", "429"}),
        ("get", "/players/{player_id}/contract", {"401", "403", "404"}),
        ("post", "/ask", {"429", "502", "503"}),
    ],
)
def test_representative_error_responses_are_documented(spec, method, path, codes):
    responses = spec["paths"][path][method]["responses"]
    assert codes <= set(responses)
    for code in codes:
        schema = responses[code]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse")


def test_response_models_reject_undeclared_fields():
    models = [
        value
        for value in vars(schemas).values()
        if isinstance(value, type) and issubclass(value, schemas.Schema)
    ]
    assert len(models) > 30
    assert all(model.model_config.get("extra") == "forbid" for model in models)
    with pytest.raises(ValidationError):
        schemas.GamePrediction.model_validate(
            {
                "home": "T1",
                "away": "T4",
                "season": "2025-26",
                "basis_season": "2025-26",
                "projection_mode": "season_to_date",
                "home_win_prob": 0.6,
                "undocumented": True,
            }
        )
    assert issubclass(schemas.Schema, BaseModel)
