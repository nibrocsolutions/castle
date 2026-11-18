"""One tick of Feldstein.

The phone sends stick positions and button edges. Guards, shots, locks,
and surrenders are resolved here, in the current room only. Other rooms
stay as they were left, which is how the 1981 game behaved.
"""

from __future__ import annotations

import json
import math
import random

from app.castle import floor_name, generate_castle, rank_name

PLAYER_R = 0.32
ACTOR_R = 0.3
SPEED = 2.2
GUARD_SPEED = 1.05
ALERT_SPEED = 1.4
BULLET_SPEED = 9.0
GRENADE_SPEED = 5.0
GRENADE_FUSE = 0.8
BLAST_R = 1.85
MAX_BULLETS = 10
MAX_GRENADES = 3

_ACTIONS = {"fire", "grenade", "use", "holster"}


def scratch_state() -> dict:
    """A single empty room, used by tests and not by the campaign."""
    from app.castle import _new_player, _shell

    room = _shell(0, 0, 0)
    room["cell"] = True
    return {
        "seed": 1,
        "rank": 0,
        "floors": 1,
        "cols": 1,
        "rows": 1,
        "rng": 1,
        "next_id": 20,
        "rooms": {room["id"]: room},
        "doors": [],
        "player": _new_player(room["id"], 4.5, 4.5),
        "spawn": {"room": room["id"], "x": 4.5, "y": 4.5},
        "projectiles": [],
        "blasts": [],
        "visited": [room["id"]],
        "status": "playing",
        "death": None,
        "plans_chest": None,
        "plans_room": room["id"],
        "say": "",
        "say_kind": "info",
        "say_seq": 0,
        "log": [],
        "time": 0.0,
        "rev": 0,
        "picking": None,
    }


def clean_cmd(raw: object) -> dict:
    if not isinstance(raw, dict):
        raw = {}

    def pair(value: object) -> list[float]:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return [0.0, 0.0]
        out = []
        for item in list(value)[:2]:
            try:
                number = float(item)
            except (TypeError, ValueError):
                number = 0.0
            out.append(max(-1.0, min(1.0, number)))
        return out

    pressed = []
    for name in raw.get("pressed") or []:
        if name in _ACTIONS and name not in pressed:
            pressed.append(name)
    return {"move": pair(raw.get("move")), "aim": pair(raw.get("aim")), "pressed": pressed, "use": bool(raw.get("use"))}


def step(state: dict, cmd: object, dt: float) -> None:
    dt = max(0.0, min(float(dt), 0.25))
    cmd = clean_cmd(cmd)
    state["rev"] = int(state.get("rev", 0)) + 1
    state["time"] = float(state.get("time", 0.0)) + dt
    state["_q"] = {}
    state["picking"] = None
    _decay(state, dt)
    if state["status"] != "playing":
        _commit_say(state)
        return
    player = state["player"]
    if player["stun"] <= 0:
        if "holster" in cmd["pressed"]:
            player["holstered"] = not player["holstered"]
        _move_player(state, cmd, dt)
        if state["status"] == "playing":
            _use(state, cmd, dt)
        if state["status"] == "playing" and "fire" in cmd["pressed"]:
            _fire(state)
        if state["status"] == "playing" and "grenade" in cmd["pressed"]:
            _throw(state)
    if state["status"] == "playing":
        room = _room(state)
        for guard in room["guards"]:
            _update_guard(state, room, guard, dt)
            if state["status"] != "playing":
                break
    if state["status"] == "playing":
        _projectiles(state, dt)
    _commit_say(state)


def dump_state(state: dict) -> str:
    clean = {key: value for key, value in state.items() if not str(key).startswith("_")}
    return json.dumps(clean, separators=(",", ":"))


def continue_after_death(state: dict, seed: int | None = None) -> dict:
    if state.get("status") != "dead":
        return state
    if state.get("death") == "explosive":
        new_seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)
        fresh = generate_castle(int(state["rank"]), int(new_seed))
        line = "The blast brings the wing down. This castle is a new one."
        fresh["say"] = line
        fresh["say_kind"] = "info"
        fresh["say_seq"] = 1
        fresh["log"] = [line, "A dying prisoner gives you a pistol and three grenades."]
        return fresh
    spawn = state["spawn"]
    from app.castle import _new_player

    state["player"] = _new_player(spawn["room"], spawn["x"], spawn["y"])
    for room in state["rooms"].values():
        for chest in room["chests"]:
            chest["open"] = False
            chest["progress"] = 0.0
        for guard in room["guards"]:
            guard["x"] = guard["home"][0]
            guard["y"] = guard["home"][1]
            guard["facing"] = guard.get("home_facing", guard["facing"])
            guard["hp"] = guard["max_hp"]
            guard["state"] = "patrol"
            guard["searched"] = False
            guard["surrender_t"] = 0.0
            guard["alert_for"] = 0.0
            guard["stuck"] = 0.0
            guard["cooldown"] = 0.6
            guard["pi"] = 0
            guard["said_halt"] = False
            guard["said_give"] = False
            guard["said_ss"] = False
    state["projectiles"] = []
    state["blasts"] = []
    state["status"] = "playing"
    state["death"] = None
    state["picking"] = None
    line = "You wake in the cell. The sentries are back on their posts."
    state["say"] = line
    state["say_kind"] = "info"
    state["say_seq"] = int(state.get("say_seq", 0)) + 1
    state["log"] = list(state.get("log") or [])[-4:] + [line]
    state["log"] = state["log"][-5:]
    return state


def public_view(state: dict) -> dict:
    player = state["player"]
    room = state["rooms"][player["room"]]
    floor = room["floor"]
    floors = int(state["floors"])
    seen = set(state.get("visited") or [])
    floor_map = []
    for other in state["rooms"].values():
        if other["floor"] != floor:
            continue
        been = other["id"] in seen
        mark = ""
        if been and other.get("exit"):
            mark = "exit"
        elif been and other.get("cell"):
            mark = "cell"
        floor_map.append(
            {
                "gx": other["gx"],
                "gy": other["gy"],
                "seen": been,
                "here": other["id"] == room["id"],
                "mark": mark,
            }
        )
    floor_map.sort(key=lambda cell: (cell["gy"], cell["gx"]))
    return {
        "status": state["status"],
        "death": state.get("death"),
        "rank": state["rank"],
        "rank_name": rank_name(int(state["rank"])),
        "floor": floor,
        "floors": floors,
        "floor_name": floor_name(floor, floors),
        "room_id": room["id"],
        "time": int(state.get("time", 0)),
        "rev": state.get("rev", 0),
        "say": state.get("say") or "",
        "say_kind": state.get("say_kind") or "info",
        "say_seq": state.get("say_seq", 0),
        "log": list(state.get("log") or [])[-4:],
        "picking": state.get("picking"),
        "room": {
            "w": room["w"],
            "h": room["h"],
            "tiles": room["tiles"],
            "exit": bool(room.get("exit")),
            "cell": bool(room.get("cell")),
        },
        "chests": [
            {
                "id": chest["id"],
                "x": chest["x"],
                "y": chest["y"],
                "open": chest["open"],
                "progress": chest["progress"],
                "need": chest["need"],
            }
            for chest in room["chests"]
        ],
        "guards": [
            {
                "id": guard["id"],
                "x": guard["x"],
                "y": guard["y"],
                "kind": guard["kind"],
                "state": guard["state"],
                "facing": guard["facing"],
                "hp": guard["hp"],
            }
            for guard in room["guards"]
        ],
        "projectiles": [
            {"id": shot["id"], "x": shot["x"], "y": shot["y"], "kind": shot["kind"]}
            for shot in state.get("projectiles") or []
        ],
        "blasts": list(state.get("blasts") or []),
        "player": {
            "x": player["x"],
            "y": player["y"],
            "aim": player["aim"],
            "bullets": player["bullets"],
            "grenades": player["grenades"],
            "keys": player["keys"],
            "uniform": player["uniform"],
            "vest": player["vest"],
            "plans": player["plans"],
            "holstered": player["holstered"],
            "stun": player["stun"],
            "drunk": player["drunk"],
        },
        "map": floor_map,
    }


def _decay(state: dict, dt: float) -> None:
    player = state["player"]
    for key in ("stun", "bonk", "drunk", "cooldown", "enter_lock", "grenade_cd"):
        player[key] = max(0.0, float(player.get(key, 0.0)) - dt)
    for blast in state.get("blasts") or []:
        blast["life"] = float(blast.get("life", 0.0)) - dt
    state["blasts"] = [blast for blast in state.get("blasts") or [] if blast["life"] > 0]


def _move_player(state: dict, cmd: dict, dt: float) -> None:
    player = state["player"]
    mx, my = cmd["move"]
    mag = math.hypot(mx, my)
    ax, ay = cmd["aim"]
    if math.hypot(ax, ay) > 0.35:
        player["aim"] = math.atan2(ay, ax)
    elif mag >= 0.2:
        player["aim"] = math.atan2(my, mx)
    if mag < 0.2:
        return
    mx, my = mx / mag, my / mag
    distance = SPEED * dt
    steps = max(1, int(distance / 0.18) + 1)
    sub = dt / steps
    blocked = False
    for _ in range(steps):
        if state["status"] != "playing":
            return
        room = _room(state)
        ox, oy = player["x"], player["y"]
        player["x"], player["y"] = _slide(room, ox, oy, mx * SPEED * sub, my * SPEED * sub, PLAYER_R)
        blocked = abs(player["x"] - ox) + abs(player["y"] - oy) <= 0.0001
        if _maybe_leave(state):
            return
    if blocked and player["bonk"] <= 0:
        player["stun"] = 0.42
        player["bonk"] = 0.9
        _bark(state, "You stumble into the stone.", "info")


def _maybe_leave(state: dict) -> bool:
    player = state["player"]
    if player["enter_lock"] > 0:
        return False
    room = _room(state)
    tx, ty = int(player["x"]), int(player["y"])
    tile = _tile(room, tx, ty)
    if tile == "e":
        state["status"] = "escaped"
        if player["plans"]:
            _bark(state, "You are out, and the plans are with you.", "info")
        else:
            _bark(state, "You are out. The plans are still inside.", "info")
        return True
    if tile == "u" and room.get("up"):
        dest = room["up"]
        _arrive(state, dest["room"], dest["x"], dest["y"])
        return True
    if tile == "n" and room.get("down"):
        dest = room["down"]
        _arrive(state, dest["room"], dest["x"], dest["y"])
        return True
    if tile != "d":
        return False
    door, side = _door_at(state, room["id"], tx, ty)
    if not door or not door["open"] or side is None:
        return False
    other = door["b"] if side == "a" else door["a"]
    if any(guard["state"] == "alert" for guard in room["guards"]):
        _bark(state, "Schweinhund!", "bark")
    _arrive(state, other["room"], other["inward"][0], other["inward"][1])
    if _room(state).get("exit"):
        _bark(state, "The rampart gate.", "info")
    return True


def _arrive(state: dict, room_id: str, x: float, y: float) -> None:
    player = state["player"]
    player["room"] = room_id
    player["x"] = float(x)
    player["y"] = float(y)
    player["enter_lock"] = 0.4
    visited = state.setdefault("visited", [])
    if room_id not in visited:
        visited.append(room_id)
    state["projectiles"] = []


def _use(state: dict, cmd: dict, dt: float) -> None:
    room = _room(state)
    player = state["player"]
    if "use" in cmd["pressed"]:
        body = _nearest_body(room, player)
        if body is not None:
            _search(state, body)
            return
        door = _nearest_locked_door(state, room, player)
        if door is not None:
            if player["keys"] > 0:
                player["keys"] -= 1
                _open_door(state, door)
                _bark(state, "The key turns.", "info")
            else:
                _bark(state, "Locked.", "info")
            return
    if not cmd["use"]:
        _decay_picks(room, dt)
        return
    chest = _nearest_chest(room, player)
    if chest is None:
        _decay_picks(room, dt)
        return
    for other in room["chests"]:
        if other is not chest and not other["open"]:
            other["progress"] = max(0.0, other["progress"] - dt * 0.35)
    chest["progress"] = min(float(chest["need"]), float(chest["progress"]) + dt)
    state["picking"] = {"id": chest["id"], "progress": chest["progress"], "need": chest["need"]}
    if chest["progress"] >= chest["need"]:
        _finish_chest(state, chest)


def _decay_picks(room: dict, dt: float) -> None:
    for chest in room["chests"]:
        if not chest["open"]:
            chest["progress"] = max(0.0, float(chest["progress"]) - dt * 0.35)


def _search(state: dict, guard: dict) -> None:
    if guard["searched"]:
        _bark(state, "Nothing left.", "info")
        return
    guard["searched"] = True
    if not guard["loot"]:
        _bark(state, "Nothing useful.", "info")
        return
    _bark(state, " ".join(give(state, item["kind"], int(item["amount"])) for item in guard["loot"]), "info")


def _finish_chest(state: dict, chest: dict) -> None:
    if chest["open"]:
        return
    chest["open"] = True
    chest["progress"] = chest["need"]
    state["picking"] = None
    if not chest["contents"]:
        _bark(state, "Empty.", "info")
        return
    _bark(state, " ".join(give(state, item["kind"], int(item["amount"])) for item in chest["contents"]), "info")


def give(state: dict, kind: str, amount: int) -> str:
    player = state["player"]
    amount = max(1, amount)
    if kind == "bullets":
        room = MAX_BULLETS - player["bullets"]
        got = min(room, amount)
        player["bullets"] += got
        return "Bullets." if got else "No room for bullets."
    if kind == "grenade":
        room = MAX_GRENADES - player["grenades"]
        got = min(room, amount)
        player["grenades"] += got
        return "A grenade." if got else "No room for a grenade."
    if kind == "key":
        player["keys"] += amount
        return "A key."
    if kind == "uniform":
        if player["uniform"]:
            return "Another coat."
        player["uniform"] = True
        return "An enemy coat."
    if kind == "vest":
        if player["vest"]:
            return "Another vest."
        player["vest"] = True
        return "A vest."
    if kind == "plans":
        player["plans"] = True
        return "The war plans."
    if kind == "schnapps":
        player["drunk"] = max(float(player["drunk"]), 9.0)
        return "Schnapps. Your aim swims."
    if kind == "sausage":
        return "Sausage."
    if kind == "sauerkraut":
        return "Sauerkraut."
    return "Nothing useful."


def _fire(state: dict) -> None:
    player = state["player"]
    if player["cooldown"] > 0:
        return
    if player["holstered"]:
        player["holstered"] = False
    if player["bullets"] <= 0:
        player["cooldown"] = 0.25
        _bark(state, "The pistol is empty.", "info")
        return
    player["bullets"] -= 1
    player["cooldown"] = 0.34
    aim = float(player["aim"])
    if player["drunk"] > 0:
        aim += _rng(state).uniform(-0.38, 0.38)
    _spawn_bullet(state, player["x"], player["y"], aim, "player")
    _alert(state, 6.0)


def _throw(state: dict) -> None:
    player = state["player"]
    if player["grenade_cd"] > 0:
        return
    if player["grenades"] <= 0:
        _bark(state, "No grenades.", "info")
        return
    player["grenades"] -= 1
    player["grenade_cd"] = 0.45
    aim = float(player["aim"])
    ox = math.cos(aim) * 0.55
    oy = math.sin(aim) * 0.55
    state["projectiles"].append(
        {
            "id": _nid(state),
            "x": player["x"] + ox,
            "y": player["y"] + oy,
            "vx": math.cos(aim) * GRENADE_SPEED,
            "vy": math.sin(aim) * GRENADE_SPEED,
            "kind": "grenade",
            "owner": "player",
            "fuse": GRENADE_FUSE,
            "room": player["room"],
        }
    )
    _alert(state, 6.0)


def _spawn_bullet(state: dict, x: float, y: float, aim: float, owner: str) -> None:
    state["projectiles"].append(
        {
            "id": _nid(state),
            "x": x + math.cos(aim) * 0.55,
            "y": y + math.sin(aim) * 0.55,
            "vx": math.cos(aim) * BULLET_SPEED,
            "vy": math.sin(aim) * BULLET_SPEED,
            "kind": "bullet",
            "owner": owner,
            "fuse": 0.0,
            "room": state["player"]["room"],
        }
    )


def _projectiles(state: dict, dt: float) -> None:
    room = _room(state)
    kept = []
    for proj in state["projectiles"]:
        if proj["room"] != room["id"] or state["status"] != "playing":
            continue
        done = _advance_grenade(state, room, proj, dt) if proj["kind"] == "grenade" else _advance_bullet(state, room, proj, dt)
        if not done and state["status"] == "playing":
            kept.append(proj)
    state["projectiles"] = kept


def _advance_bullet(state: dict, room: dict, proj: dict, dt: float) -> bool:
    steps = 4
    for _ in range(steps):
        proj["x"] += proj["vx"] * dt / steps
        proj["y"] += proj["vy"] * dt / steps
        tx, ty = int(proj["x"]), int(proj["y"])
        tile = _tile(room, tx, ty)
        if tile == "D":
            door, _side = _door_at(state, room["id"], tx, ty)
            if door:
                _open_door(state, door)
            _alert(state, 6.0)
            _bark(state, "The door gives.", "info")
            return True
        if tile == "#":
            return True
        if proj["owner"] == "player":
            for guard in room["guards"]:
                if guard["state"] == "dead":
                    continue
                if math.hypot(guard["x"] - proj["x"], guard["y"] - proj["y"]) <= 0.42:
                    _hurt_guard(state, guard, 1)
                    return True
            for chest in room["chests"]:
                if chest["open"]:
                    continue
                if math.hypot(chest["x"] - proj["x"], chest["y"] - proj["y"]) <= 0.45:
                    _shot_chest(state, chest)
                    return True
        elif math.hypot(state["player"]["x"] - proj["x"], state["player"]["y"] - proj["y"]) <= 0.36:
            _hurt_player(state, "bullet")
            return True
    return False


def _advance_grenade(state: dict, room: dict, proj: dict, dt: float) -> bool:
    proj["fuse"] = float(proj["fuse"]) - dt
    hit = False
    for _ in range(3):
        proj["x"] += proj["vx"] * dt / 3
        proj["y"] += proj["vy"] * dt / 3
        if _tile(room, int(proj["x"]), int(proj["y"])) in {"#", "D"}:
            hit = True
            break
    if hit or proj["fuse"] <= 0:
        _explode(state, room, proj["x"], proj["y"])
        return True
    return False


def _explode(state: dict, room: dict, x: float, y: float) -> None:
    state["blasts"].append({"x": x, "y": y, "r": BLAST_R, "life": 0.32})
    player = state["player"]
    if math.hypot(player["x"] - x, player["y"] - y) <= BLAST_R:
        _hurt_player(state, "explosive")
    for guard in room["guards"]:
        if guard["state"] != "dead" and math.hypot(guard["x"] - x, guard["y"] - y) <= BLAST_R:
            _hurt_guard(state, guard, 8)
    for chest in room["chests"]:
        if chest["open"] or not chest.get("explosive"):
            continue
        if math.hypot(chest["x"] - x, chest["y"] - y) <= BLAST_R:
            chest["open"] = True
            _hurt_player(state, "explosive")
    _alert(state, 6.0)


def _shot_chest(state: dict, chest: dict) -> None:
    if chest.get("explosive"):
        chest["open"] = True
        _bark(state, "Explosives!", "info")
        state["blasts"].append({"x": chest["x"], "y": chest["y"], "r": BLAST_R, "life": 0.32})
        _hurt_player(state, "explosive")
        _alert(state, 6.0)
        return
    chest["progress"] = max(float(chest["progress"]), float(chest["need"]) * 0.72)
    _bark(state, "The lock splinters.", "info")
    _alert(state, 6.0)


def _hurt_player(state: dict, cause: str) -> None:
    if state["status"] != "playing":
        return
    player = state["player"]
    if cause == "bullet" and player["vest"]:
        player["vest"] = False
        _bark(state, "The vest catches the bullet.", "info")
        return
    state["status"] = "dead"
    state["death"] = "explosive" if cause == "explosive" else "bullet"
    if cause == "explosive":
        _bark(state, "The blast takes the room.", "info")
    else:
        _bark(state, "Caught.", "info")


def _hurt_guard(state: dict, guard: dict, amount: int) -> None:
    if guard["state"] == "dead":
        return
    guard["hp"] = int(guard["hp"]) - amount
    if guard["hp"] <= 0:
        guard["hp"] = 0
        guard["state"] = "dead"
        _bark(state, "Mein Leben!", "bark")
        return
    if guard["state"] != "surrender":
        guard["state"] = "alert"
        guard["alert_for"] = max(float(guard["alert_for"]), 4.0)


def _update_guard(state: dict, room: dict, guard: dict, dt: float) -> None:
    if guard["state"] == "dead" or state["status"] != "playing":
        return
    guard["cooldown"] = max(0.0, float(guard["cooldown"]) - dt)
    player = state["player"]
    if _aimed_at(room, guard, player) and guard["kind"] == "guard":
        guard["surrender_t"] = float(guard["surrender_t"]) + dt
        guard["facing"] = math.atan2(player["y"] - guard["y"], player["x"] - guard["x"])
        if guard["surrender_t"] >= float(guard["giveup"]):
            guard["state"] = "surrender"
            if not guard["said_give"]:
                guard["said_give"] = True
                _bark(state, "Kamerad!", "bark")
        else:
            guard["state"] = "alert"
        return
    guard["surrender_t"] = max(0.0, float(guard["surrender_t"]) - dt * 0.5)
    if guard["state"] == "surrender":
        guard["facing"] = math.atan2(player["y"] - guard["y"], player["x"] - guard["x"])
        return
    if _sees(room, guard, player):
        guard["state"] = "alert"
        guard["alert_for"] = max(float(guard["alert_for"]), 5.0)
        if not guard["said_halt"]:
            guard["said_halt"] = True
            if guard["kind"] == "ss":
                guard["said_ss"] = True
                _bark(state, "Schweinhund!", "bark")
            else:
                _bark(state, "Halt!", "bark")
    if guard["state"] == "alert":
        _chase(room, guard, player, dt)
        if _los(room, guard["x"], guard["y"], player["x"], player["y"]) and _distance(guard, player) < 7.2:
            _maybe_shoot(state, guard, player)
        guard["alert_for"] = float(guard["alert_for"]) - dt
        if guard["alert_for"] <= 0 and not _sees(room, guard, player):
            guard["state"] = "patrol"
            guard["said_halt"] = False
        return
    _patrol(room, guard, dt)


def _chase(room: dict, guard: dict, player: dict, dt: float) -> None:
    dx = player["x"] - guard["x"]
    dy = player["y"] - guard["y"]
    dist = math.hypot(dx, dy) or 0.001
    guard["facing"] = math.atan2(dy, dx)
    if dist <= 1.9:
        return
    step = ALERT_SPEED * dt
    guard["x"], guard["y"] = _slide(room, guard["x"], guard["y"], dx / dist * step, dy / dist * step, ACTOR_R)


def _patrol(room: dict, guard: dict, dt: float) -> None:
    points = guard.get("patrol") or []
    if len(points) < 2:
        return
    tx, ty = points[int(guard["pi"]) % len(points)]
    dx, dy = tx - guard["x"], ty - guard["y"]
    dist = math.hypot(dx, dy)
    if dist < 0.2:
        guard["pi"] = (int(guard["pi"]) + 1) % len(points)
        guard["stuck"] = 0.0
        return
    step = GUARD_SPEED * dt
    ux, uy = dx / dist, dy / dist
    guard["facing"] = math.atan2(uy, ux)
    nx, ny = _slide(room, guard["x"], guard["y"], ux * step, uy * step, ACTOR_R)
    if math.hypot(nx - guard["x"], ny - guard["y"]) < step * 0.3:
        guard["stuck"] = float(guard.get("stuck", 0.0)) + dt
        if guard["stuck"] > 1.4:
            guard["pi"] = (int(guard["pi"]) + 1) % len(points)
            guard["stuck"] = 0.0
    else:
        guard["stuck"] = 0.0
    guard["x"], guard["y"] = nx, ny


def _maybe_shoot(state: dict, guard: dict, player: dict) -> None:
    if guard["cooldown"] > 0 or guard["state"] == "dead":
        return
    guard["cooldown"] = 0.95 if guard["kind"] == "ss" else 1.15
    aim = math.atan2(player["y"] - guard["y"], player["x"] - guard["x"])
    aim += _rng(state).uniform(-0.1, 0.1)
    _spawn_bullet(state, guard["x"], guard["y"], aim, "guard")


def _aimed_at(room: dict, guard: dict, player: dict) -> bool:
    if player["holstered"] or guard["state"] == "dead":
        return False
    dx, dy = guard["x"] - player["x"], guard["y"] - player["y"]
    dist = math.hypot(dx, dy)
    if dist > 3.6 or dist < 0.05:
        return False
    if abs(_angle_diff(math.atan2(dy, dx), float(player["aim"]))) > 0.45:
        return False
    return _los(room, player["x"], player["y"], guard["x"], guard["y"])


def _sees(room: dict, guard: dict, player: dict) -> bool:
    if guard["state"] == "dead":
        return False
    dx, dy = player["x"] - guard["x"], player["y"] - guard["y"]
    dist = math.hypot(dx, dy)
    if dist > 7.2 or not _los(room, guard["x"], guard["y"], player["x"], player["y"]):
        return False
    diff = abs(_angle_diff(math.atan2(dy, dx), float(guard["facing"])))
    disguised = bool(player["uniform"]) and guard["kind"] != "ss"
    if disguised and player["holstered"]:
        return diff < 1.05 and dist < 1.2
    if disguised and not player["holstered"]:
        return dist < 2.3 or diff < 0.7
    if dist < 1.15:
        return True
    cone = 1.2 if guard["state"] == "alert" else 0.7
    return diff < cone


def _los(room: dict, x0: float, y0: float, x1: float, y1: float) -> bool:
    dist = math.hypot(x1 - x0, y1 - y0)
    steps = max(1, int(dist / 0.2))
    for index in range(1, steps):
        t = index / steps
        tile = _tile(room, int(x0 + (x1 - x0) * t), int(y0 + (y1 - y0) * t))
        if tile in {"#", "D"}:
            return False
    return True


def _alert(state: dict, duration: float) -> None:
    for guard in _room(state)["guards"]:
        if guard["state"] in {"dead", "surrender"}:
            continue
        guard["state"] = "alert"
        guard["alert_for"] = max(float(guard.get("alert_for", 0.0)), duration)


def _open_door(state: dict, door: dict) -> None:
    door["open"] = True
    door["locked"] = False
    for side in ("a", "b"):
        room = state["rooms"][door[side]["room"]]
        for x, y in door[side]["tiles"]:
            _set_tile(room, int(x), int(y), "d")


def _door_at(state: dict, room_id: str, tx: int, ty: int) -> tuple[dict | None, str | None]:
    for door in state["doors"]:
        for side in ("a", "b"):
            if door[side]["room"] != room_id:
                continue
            for tile in door[side]["tiles"]:
                if int(tile[0]) == tx and int(tile[1]) == ty:
                    return door, side
    return None, None


def _nearest_body(room: dict, player: dict) -> dict | None:
    best = None
    best_dist = 1.25
    for guard in room["guards"]:
        if guard["state"] not in {"dead", "surrender"}:
            continue
        dist = _distance(guard, player)
        if dist < best_dist:
            best = guard
            best_dist = dist
    return best


def _nearest_chest(room: dict, player: dict) -> dict | None:
    best = None
    best_dist = 1.3
    for chest in room["chests"]:
        if chest["open"]:
            continue
        dist = math.hypot(chest["x"] - player["x"], chest["y"] - player["y"])
        if dist < best_dist:
            best = chest
            best_dist = dist
    return best


def _nearest_locked_door(state: dict, room: dict, player: dict) -> dict | None:
    best = None
    best_dist = 1.05
    for door in state["doors"]:
        if door["open"]:
            continue
        for side in ("a", "b"):
            if door[side]["room"] != room["id"]:
                continue
            for tile in door[side]["tiles"]:
                dist = _reach(player["x"], player["y"], int(tile[0]), int(tile[1]))
                if dist < best_dist:
                    best = door
                    best_dist = dist
    return best


def _reach(px: float, py: float, tx: int, ty: int) -> float:
    cx = min(max(px, tx), tx + 1)
    cy = min(max(py, ty), ty + 1)
    return math.hypot(px - cx, py - cy)


def _slide(room: dict, x: float, y: float, dx: float, dy: float, radius: float) -> tuple[float, float]:
    nx = x + dx
    if not _hits(room, nx, y, radius):
        x = nx
    ny = y + dy
    if not _hits(room, x, ny, radius):
        y = ny
    return x, y


def _hits(room: dict, x: float, y: float, radius: float) -> bool:
    min_x = int(math.floor(x - radius))
    max_x = int(math.floor(x + radius))
    min_y = int(math.floor(y - radius))
    max_y = int(math.floor(y + radius))
    for ty in range(min_y, max_y + 1):
        for tx in range(min_x, max_x + 1):
            if _tile(room, tx, ty) not in {"#", "D"}:
                continue
            closest_x = min(max(x, tx), tx + 1)
            closest_y = min(max(y, ty), ty + 1)
            if (x - closest_x) ** 2 + (y - closest_y) ** 2 < radius * radius - 1e-8:
                return True
    return False


def _tile(room: dict, x: int, y: int) -> str:
    if x < 0 or y < 0 or x >= room["w"] or y >= room["h"]:
        return "#"
    return room["tiles"][y * room["w"] + x]


def _set_tile(room: dict, x: int, y: int, char: str) -> None:
    index = y * room["w"] + x
    tiles = room["tiles"]
    room["tiles"] = tiles[:index] + char + tiles[index + 1 :]


def _room(state: dict) -> dict:
    return state["rooms"][state["player"]["room"]]


def _distance(actor: dict, player: dict) -> float:
    return math.hypot(actor["x"] - player["x"], actor["y"] - player["y"])


def _angle_diff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def _rng(state: dict) -> random.Random:
    rng = random.Random(int(state.get("rng") or 1))
    state["rng"] = rng.randrange(1, 2**31 - 1)
    return rng


def _nid(state: dict) -> int:
    state["next_id"] = int(state.get("next_id", 1)) + 1
    return int(state["next_id"])


def _bark(state: dict, text: str, kind: str = "info") -> None:
    state.setdefault("_q", {})
    state["_q"]["info" if kind == "info" else "bark"] = text


def _commit_say(state: dict) -> None:
    queued = state.pop("_q", None) or {}
    if "info" in queued:
        text, kind = queued["info"], "info"
    elif "bark" in queued:
        text, kind = queued["bark"], "bark"
    else:
        return
    if text == state.get("say"):
        if kind == "bark":
            state["say_seq"] = int(state.get("say_seq", 0)) + 1
        return
    state["say"] = text
    state["say_kind"] = kind
    state["say_seq"] = int(state.get("say_seq", 0)) + 1
    log = list(state.get("log") or [])
    log.append(text)
    state["log"] = log[-5:]
