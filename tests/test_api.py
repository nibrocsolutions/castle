import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from app.database import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_a_player_can_resume_the_same_castle(client):
    created = client.post("/api/players", json={"name": "Ada"})
    assert created.status_code == 201
    player_id = created.json()["id"]
    first = client.post("/api/runs", json={"player_id": player_id})
    assert first.status_code == 201
    assert first.json()["resumed"] is False
    again = client.post("/api/runs", json={"player_id": player_id})
    assert again.json()["resumed"] is True
    assert again.json()["run"]["id"] == first.json()["run"]["id"]
    home = client.get("/api/home", params={"player_id": player_id}).json()
    assert home["active"]["id"] == first.json()["run"]["id"]
    assert home["player"]["rank_name"] == "Private"
    view = client.get(f"/api/runs/{first.json()['run']['id']}", params={"player_id": player_id}).json()["view"]
    blob = str(view)
    assert "contents" not in blob
    assert "loot" not in blob
    assert view["player"]["bullets"] == 10


def test_duplicate_names_are_refused(client):
    assert client.post("/api/players", json={"name": "Ada"}).status_code == 201
    assert client.post("/api/players", json={"name": " ada "}).status_code == 409


def test_play_socket_moves_the_prisoner(client):
    player_id = client.post("/api/players", json={"name": "Bea"}).json()["id"]
    run_id = client.post("/api/runs", json={"player_id": player_id}).json()["run"]["id"]
    with client.websocket_connect(f"/api/runs/{run_id}/play?player_id={player_id}") as socket:
        hello = socket.receive_json()
        start = hello["player"]["x"]
        socket.send_json({"cmd": "input", "move": [1, 0], "aim": [1, 0], "pressed": [], "use": False})
        moved = socket.receive_json()
    assert moved["player"]["x"] >= start
    assert moved["room_id"] == hello["room_id"]
