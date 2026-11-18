import json

from app.castle import generate_castle
from app.game import continue_after_death, give, public_view, scratch_state, step


def _quiet():
    return {"move": [0, 0], "aim": [0, 0], "pressed": [], "use": False}


def test_walking_and_bonking():
    state = scratch_state()
    for _ in range(4):
        step(state, {"move": [1, 0], "aim": [0, 0], "pressed": [], "use": False}, 0.25)
    assert state["player"]["x"] > 6.4
    assert state["player"]["stun"] == 0
    state["player"]["x"] = 1.45
    state["player"]["bonk"] = 0
    step(state, {"move": [-1, 0], "aim": [0, 0], "pressed": [], "use": False}, 0.4)
    assert state["player"]["stun"] > 0
    assert "stone" in state["say"]


def test_a_pistol_drops_a_sentry_and_a_search_loots_him():
    state = scratch_state()
    guard = {
        "id": 1,
        "x": 7.2,
        "y": 4.5,
        "home": [7.2, 4.5],
        "home_facing": 0,
        "kind": "guard",
        "hp": 2,
        "max_hp": 2,
        "facing": 0,
        "state": "patrol",
        "patrol": [],
        "pi": 0,
        "stuck": 0,
        "cooldown": 5,
        "surrender_t": 0,
        "giveup": 1,
        "alert_for": 0,
        "searched": False,
        "loot": [{"kind": "key", "amount": 1}],
        "said_halt": False,
        "said_give": False,
        "said_ss": False,
    }
    state["rooms"]["0,0,0"]["guards"].append(guard)
    state["player"].update(x=4.5, y=4.5, aim=0, bullets=10, holstered=False, cooldown=0)
    step(state, {"move": [0, 0], "aim": [1, 0], "pressed": ["fire"], "use": False}, 0.05)
    assert state["player"]["bullets"] == 9
    for _ in range(12):
        step(state, _quiet(), 0.1)
    assert guard["hp"] < 2
    guard["state"] = "dead"
    state["player"]["x"] = 6.6
    step(state, {"move": [0, 0], "aim": [1, 0], "pressed": ["use"], "use": False}, 0.1)
    assert state["player"]["keys"] == 1
    assert guard["searched"] is True


def test_uniform_fools_a_sentry_until_you_aim_and_he_gives_up():
    state = scratch_state()
    guard = {
        "id": 2,
        "x": 6.5,
        "y": 4.5,
        "home": [6.5, 4.5],
        "home_facing": 3.14,
        "kind": "guard",
        "hp": 2,
        "max_hp": 2,
        "facing": 3.14,
        "state": "patrol",
        "patrol": [],
        "pi": 0,
        "stuck": 0,
        "cooldown": 0,
        "surrender_t": 0,
        "giveup": 0.25,
        "alert_for": 0,
        "searched": False,
        "loot": [],
        "said_halt": False,
        "said_give": False,
        "said_ss": False,
    }
    state["rooms"]["0,0,0"]["guards"].append(guard)
    state["player"].update(x=3.4, y=4.5, uniform=True, holstered=True, aim=0)
    step(state, _quiet(), 0.2)
    assert guard["state"] == "patrol"
    state["player"]["holstered"] = False
    state["player"]["aim"] = 0
    for _ in range(6):
        step(state, {"move": [0, 0], "aim": [1, 0], "pressed": [], "use": False}, 0.1)
    assert guard["state"] == "surrender"
    assert state["say"] == "Kamerad!"


def test_storm_guard_is_not_fooled_by_a_coat():
    state = scratch_state()
    guard = {
        "id": 3,
        "x": 6.5,
        "y": 4.5,
        "home": [6.5, 4.5],
        "home_facing": 3.14,
        "kind": "ss",
        "hp": 5,
        "max_hp": 5,
        "facing": 3.14,
        "state": "patrol",
        "patrol": [],
        "pi": 0,
        "stuck": 0,
        "cooldown": 5,
        "surrender_t": 0,
        "giveup": 0.2,
        "alert_for": 0,
        "searched": False,
        "loot": [],
        "said_halt": False,
        "said_give": False,
        "said_ss": False,
    }
    state["rooms"]["0,0,0"]["guards"].append(guard)
    state["player"].update(x=3.6, y=4.5, uniform=True, holstered=True, aim=0)
    step(state, _quiet(), 0.2)
    assert guard["state"] == "alert"
    assert state["say"] == "Schweinhund!"


def test_lockpick_and_a_shot_speeds_the_lock():
    state = scratch_state()
    chest = {
        "id": 9,
        "x": 5.5,
        "y": 4.5,
        "locked": True,
        "open": False,
        "progress": 0.0,
        "need": 1.0,
        "explosive": False,
        "contents": [{"kind": "bullets", "amount": 4}],
    }
    state["rooms"]["0,0,0"]["chests"].append(chest)
    state["player"].update(x=4.5, y=4.5, bullets=6)
    for _ in range(3):
        step(state, {"move": [0, 0], "aim": [0, 0], "pressed": [], "use": True}, 0.2)
    assert chest["open"] is False
    for _ in range(4):
        step(state, {"move": [0, 0], "aim": [0, 0], "pressed": [], "use": True}, 0.2)
    assert chest["open"] is True
    assert state["player"]["bullets"] == 10
    assert "Bullets." in state["say"]


def test_shooting_an_explosive_chest_ends_the_castle():
    state = scratch_state()
    chest = {
        "id": 11,
        "x": 6.2,
        "y": 4.5,
        "locked": True,
        "open": False,
        "progress": 0.0,
        "need": 8.0,
        "explosive": True,
        "contents": [{"kind": "sausage", "amount": 1}],
    }
    state["rooms"]["0,0,0"]["chests"].append(chest)
    state["player"].update(x=4.5, y=4.5, aim=0, bullets=3, holstered=False, cooldown=0)
    step(state, {"move": [0, 0], "aim": [1, 0], "pressed": ["fire"], "use": False}, 0.05)
    for _ in range(10):
        if state["status"] == "dead":
            break
        step(state, _quiet(), 0.1)
    assert state["status"] == "dead"
    assert state["death"] == "explosive"


def test_bullet_death_keeps_the_seed_and_a_blast_does_not():
    state = generate_castle(1, 99)
    seed = state["seed"]
    state["status"] = "dead"
    state["death"] = "bullet"
    state["player"]["plans"] = True
    kept = continue_after_death(state)
    assert kept["seed"] == seed
    assert kept["status"] == "playing"
    assert kept["player"]["plans"] is False
    assert kept["player"]["bullets"] == 10
    blasted = generate_castle(1, 99)
    blasted["status"] = "dead"
    blasted["death"] = "explosive"
    fresh = continue_after_death(blasted, seed=12345)
    assert fresh["seed"] == 12345
    assert fresh["seed"] != 99


def test_view_hides_chest_contents_and_pockets():
    state = generate_castle(3, 5)
    view = public_view(state)
    blob = json.dumps(view)
    assert "contents" not in blob
    assert "loot" not in blob
    assert "plans" not in blob or view["player"]["plans"] is False
    assert view["room"]["tiles"]
    assert view["player"]["bullets"] == 10


def test_pockets_hold_ten_rounds_and_three_grenades():
    state = scratch_state()
    state["player"]["bullets"] = 9
    state["player"]["grenades"] = 3
    assert give(state, "bullets", 4) == "Bullets."
    assert state["player"]["bullets"] == 10
    assert give(state, "grenade", 1) == "No room for a grenade."


def test_a_first_shot_from_the_cell_is_not_a_guaranteed_death():
    quiet = {"move": [0, 0], "aim": [0, -1], "pressed": [], "use": False}
    deaths = 0
    for seed in range(24):
        state = generate_castle(0, seed)
        for _ in range(20):
            step(state, quiet, 0.1)
        step(state, {**quiet, "pressed": ["fire"]}, 0.1)
        for _ in range(10):
            step(state, quiet, 0.1)
        if state["status"] != "playing":
            deaths += 1
    assert deaths < 8


def test_a_sentry_at_arm_length_can_still_shoot_you():
    state = scratch_state()
    state["rooms"]["0,0,0"]["guards"].append(
        {
            "id": 4,
            "x": 5.5,
            "y": 4.5,
            "home": [5.5, 4.5],
            "home_facing": 3.14,
            "kind": "guard",
            "hp": 2,
            "max_hp": 2,
            "facing": 3.14,
            "state": "alert",
            "patrol": [],
            "pi": 0,
            "stuck": 0,
            "cooldown": 0,
            "surrender_t": 0,
            "giveup": 2,
            "alert_for": 5,
            "searched": False,
            "loot": [],
            "said_halt": True,
            "said_give": False,
            "said_ss": False,
        }
    )
    state["player"].update(x=4.5, y=4.5, holstered=True)
    for _ in range(25):
        step(state, {"move": [0, 0], "aim": [0, 0], "pressed": [], "use": False}, 0.1)
        if state["status"] == "dead":
            break
    assert state["status"] == "dead"
    assert state["death"] == "bullet"


def test_a_generated_castle_can_be_stepped():
    state = generate_castle(0, 3)
    cmd = {"move": [0.2, -1], "aim": [0, -1], "pressed": [], "use": False}
    for index in range(25):
        pressed = ["fire"] if index == 4 else []
        step(state, {**cmd, "pressed": pressed}, 0.1)
    assert state["status"] in {"playing", "dead", "escaped"}
    json.dumps(state)
