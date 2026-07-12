"""GET /api/graph (Graph V1, slice 4).

Mounts the real router on a bare app with a real container behind it, so the
tests exercise routing, query parsing, and serialisation together.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumos.api.routes import router
from lumos.config import Settings
from lumos.core.container import build_container


def make_client(tmp_path: Path, *, graph_enabled: bool = True) -> TestClient:
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("Tagged #home, see [[b]], mentions [[Ghost]].", encoding="utf-8")
    (notes / "b.md").write_text("The target.", encoding="utf-8")

    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "lumos.db",
        notes_path=notes,
        ollama_enabled=False,
        cloud_enabled=False,
        web_search_provider="disabled",
        ingest_notes_on_startup=False,
        graph_enabled=graph_enabled,
    )
    settings.ensure_directories()
    container = build_container(settings)
    container.ingestor.ingest_all()

    app = FastAPI()
    app.include_router(router)
    app.state.container = container
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return make_client(tmp_path)


def test_slug_returns_the_node_and_its_neighbors(client: TestClient):
    body = client.get("/api/graph", params={"slug": "a"}).json()

    assert body["enabled"] is True
    assert body["node"] == {"kind": "note", "slug": "a", "title": "A", "path": "a.md"}
    assert {(n["node"]["slug"], n["rel"], n["direction"]) for n in body["neighbors"]} == {
        ("b", "links_to", "out"),
        ("ghost", "mentions", "out"),
        ("tag:home", "tagged", "out"),
    }
    assert body["related"] == []  # no seed paths were given


def test_a_lone_path_is_both_centre_and_seed(client: TestClient):
    body = client.get("/api/graph", params={"path": "a.md"}).json()

    assert body["node"]["slug"] == "a"
    assert [n["node"]["slug"] for n in body["neighbors"]]  # centre resolved from the path
    assert body["related"] == [
        {"slug": "b", "title": "B", "path": "b.md", "connections": 1, "via": ["a.md"]}
    ]


def test_several_paths_are_seeds_only(client: TestClient):
    response = client.get("/api/graph", params=[("path", "a.md"), ("path", "b.md")])
    body = response.json()

    # Two seeds have no single centre, and each is the other's only link.
    assert body["node"] is None
    assert body["neighbors"] == []
    assert body["related"] == []


def test_unknown_node_says_so(client: TestClient):
    body = client.get("/api/graph", params={"slug": "nope"}).json()

    assert body["enabled"] is True
    assert body["node"] is None
    assert "No graph node for 'nope'" in body["detail"]


def test_a_target_is_required(client: TestClient):
    response = client.get("/api/graph")

    assert response.status_code == 400
    assert "slug=" in response.json()["detail"]


def test_disabled_graph_answers_without_touching_the_database(tmp_path: Path):
    client = make_client(tmp_path, graph_enabled=False)

    body = client.get("/api/graph", params={"slug": "a"}).json()

    assert body == {
        "enabled": False,
        "detail": (
            "Graph reads are disabled. Set LUMOS_GRAPH_ENABLED=true to turn them on — "
            "ingest already writes the graph, so no reindex is needed."
        ),
        "node": None,
        "neighbors": [],
        "related": [],
    }
    # Even the missing-target 400 never fires: disabled is answered first.
    assert client.get("/api/graph").json()["enabled"] is False
