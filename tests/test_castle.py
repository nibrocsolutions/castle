import json

from app.castle import RANKS, generate_castle


def _links(state):
    links = {room_id: set(room.get("links") or []) for room_id, room in state["rooms"].items()}
    for room in state["rooms"].values():
        if room["up"]:
            links[room["id"]].add(room["up"]["room"])
        if room["down"]:
            links[room["id"]].add(room["down"]["room"])
    return links


def _reachable(state):
    cell = next(room["id"] for room in state["rooms"].values() if room["cell"])
    links = _links(state)
    seen = {cell}
    queue = [cell]
    while queue:
        current = queue.pop()
        for nxt in links[current]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def test_every_rank_is_one_connected_castle():
    for rank, spec in enumerate(RANKS):
        state = generate_castle(rank, 1000 + rank)
        assert len(state["rooms"]) == spec["floors"] * spec["cols"] * spec["rows"]
        assert _reachable(state) == set(state["rooms"])
        exits = [room for room in state["rooms"].values() if room["exit"]]
        assert len(exits) == 1
        assert exits[0]["floor"] == spec["floors"] - 1
        plans = [
            chest
            for room in state["rooms"].values()
            for chest in room["chests"]
            if any(item["kind"] == "plans" for item in chest["contents"])
        ]
        assert len(plans) == 1
        assert plans[0]["id"] == state["plans_chest"]
        assert not plans[0]["explosive"]
        gear = {item["kind"] for room in state["rooms"].values() for chest in room["chests"] for item in chest["contents"]}
        assert "uniform" in gear
        assert "vest" in gear


def test_seed_is_stable_and_json_round_trips():
    first = generate_castle(2, 42)
    second = generate_castle(2, 42)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    revived = json.loads(json.dumps(first))
    assert revived["player"]["bullets"] == 10
    assert revived["player"]["grenades"] == 3
    assert revived["rooms"][revived["player"]["room"]]["cell"] is True


def test_cell_guard_starts_with_his_back_to_you():
    state = generate_castle(0, 7)
    cell = state["rooms"][state["spawn"]["room"]]
    assert cell["guards"], "the cell has a sentry"
    guard = cell["guards"][0]
    assert guard["kind"] == "guard"
    assert guard["y"] < state["player"]["y"]
