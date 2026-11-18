"""Procedural castle for Feldstein.

Each floor is a maze of single-screen rooms. Doors, stairs, chests, and
sentries are placed from a seed so a castle can be saved and rebuilt.
Nothing here is taken from the 1981 binary; the shape of the rules is.
"""

from __future__ import annotations

import math
import random

ROOM_W = 12
ROOM_H = 9

RANKS: tuple[dict, ...] = (
    {"name": "Private", "floors": 2, "cols": 3, "rows": 2, "ss": 0.08, "lock": 0.28},
    {"name": "Corporal", "floors": 2, "cols": 3, "rows": 3, "ss": 0.14, "lock": 0.38},
    {"name": "Sergeant", "floors": 3, "cols": 3, "rows": 3, "ss": 0.2, "lock": 0.46},
    {"name": "Lieutenant", "floors": 3, "cols": 4, "rows": 3, "ss": 0.28, "lock": 0.52},
    {"name": "Captain", "floors": 4, "cols": 4, "rows": 3, "ss": 0.34, "lock": 0.58},
    {"name": "Major", "floors": 4, "cols": 4, "rows": 4, "ss": 0.4, "lock": 0.62},
    {"name": "Colonel", "floors": 5, "cols": 4, "rows": 3, "ss": 0.48, "lock": 0.68},
    {"name": "General", "floors": 5, "cols": 4, "rows": 4, "ss": 0.55, "lock": 0.72},
)


def rank_name(rank: int) -> str:
    return RANKS[max(0, min(len(RANKS) - 1, rank))]["name"]


def floor_name(floor: int, count: int) -> str:
    if floor <= 0:
        return "Dungeon"
    if floor >= count - 1:
        return "Ramparts"
    return f"Floor {floor + 1}"


def generate_castle(rank: int, seed: int) -> dict:
    rank = max(0, min(len(RANKS) - 1, int(rank)))
    spec = RANKS[rank]
    rng = random.Random(seed)
    cols, rows, floors = spec["cols"], spec["rows"], spec["floors"]
    rooms: dict[str, dict] = {}
    doors: list[dict] = []
    seq = 1

    def nid() -> int:
        nonlocal seq
        seq += 1
        return seq

    for floor in range(floors):
        for gy in range(rows):
            for gx in range(cols):
                room = _shell(floor, gx, gy)
                rooms[room["id"]] = room
        for edge in _maze_edges(cols, rows, rng):
            (ax, ay), (bx, by) = edge
            _add_door(
                rooms,
                doors,
                nid(),
                f"{floor},{ax},{ay}",
                f"{floor},{bx},{by}",
                locked=False,
            )

    cell_id = f"0,0,{rows - 1}"
    rooms[cell_id]["cell"] = True
    _lock_doors(rooms, doors, cell_id, spec["lock"], rng)
    _add_stairs(rooms, floors, rng)
    _place_exit(rooms, floors)
    for room in _rooms_in_order(rooms):
        _obstacles(room, rng)
        _populate(room, spec, rank, rng, nid)

    plans_room = _plans_room(rooms, floors)
    plans_id = _place_plans(rooms[plans_room], rng, nid)
    _guarantee_gear(rooms, rng)
    _sprinkle_keys(rooms, doors, rng)

    spawn = _spawn_point(rooms[cell_id])
    state = {
        "seed": int(seed) & 0x7FFFFFFF,
        "rank": rank,
        "floors": floors,
        "cols": cols,
        "rows": rows,
        "rng": rng.randrange(1, 2**31),
        "next_id": seq,
        "rooms": rooms,
        "doors": doors,
        "player": _new_player(cell_id, spawn[0], spawn[1]),
        "spawn": {"room": cell_id, "x": spawn[0], "y": spawn[1]},
        "projectiles": [],
        "blasts": [],
        "visited": [cell_id],
        "status": "playing",
        "death": None,
        "plans_chest": plans_id,
        "plans_room": plans_room,
        "say": "A dying prisoner gives you a pistol and three grenades.",
        "say_kind": "info",
        "say_seq": 1,
        "log": ["A dying prisoner gives you a pistol and three grenades."],
        "time": 0.0,
        "rev": 0,
        "picking": None,
    }
    return state


def _new_player(room: str, x: float, y: float) -> dict:
    return {
        "room": room,
        "x": x,
        "y": y,
        "aim": -math.pi / 2,
        "bullets": 10,
        "grenades": 3,
        "keys": 0,
        "uniform": False,
        "vest": False,
        "plans": False,
        "holstered": True,
        "stun": 0.0,
        "bonk": 0.0,
        "drunk": 0.0,
        "cooldown": 0.0,
        "enter_lock": 0.6,
        "grenade_cd": 0.0,
    }


def _shell(floor: int, gx: int, gy: int) -> dict:
    tiles = ["." for _ in range(ROOM_W * ROOM_H)]
    for x in range(ROOM_W):
        tiles[x] = "#"
        tiles[(ROOM_H - 1) * ROOM_W + x] = "#"
    for y in range(ROOM_H):
        tiles[y * ROOM_W] = "#"
        tiles[y * ROOM_W + ROOM_W - 1] = "#"
    return {
        "id": f"{floor},{gx},{gy}",
        "floor": floor,
        "gx": gx,
        "gy": gy,
        "w": ROOM_W,
        "h": ROOM_H,
        "tiles": "".join(tiles),
        "chests": [],
        "guards": [],
        "up": None,
        "down": None,
        "exit": False,
        "cell": False,
    }


def _maze_edges(cols: int, rows: int, rng: random.Random) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    visited = {(0, 0)}
    stack = [(0, 0)]
    tree: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    while stack:
        x, y = stack[-1]
        options = []
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < cols and 0 <= ny < rows and (nx, ny) not in visited:
                options.append((nx, ny))
        if not options:
            stack.pop()
            continue
        nx, ny = rng.choice(options)
        tree.add(_edge((x, y), (nx, ny)))
        visited.add((nx, ny))
        stack.append((nx, ny))
    edges = sorted(tree)
    for y in range(rows):
        for x in range(cols):
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if nx >= cols or ny >= rows:
                    continue
                edge = _edge((x, y), (nx, ny))
                if edge in tree:
                    continue
                if rng.random() < 0.2:
                    edges.append(edge)
    return edges


def _edge(a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    return (a, b) if a <= b else (b, a)


def _add_door(rooms: dict, doors: list, door_id: int, id_a: str, id_b: str, locked: bool) -> None:
    room_a = rooms[id_a]
    room_b = rooms[id_b]
    if room_a["gx"] == room_b["gx"]:
        south, north = (room_a, room_b) if room_a["gy"] > room_b["gy"] else (room_b, room_a)
        mid = ROOM_W // 2 - 1
        tiles_south = [[mid, 0], [mid + 1, 0]]
        tiles_north = [[mid, ROOM_H - 1], [mid + 1, ROOM_H - 1]]
        inward_south = [mid + 1.0, 1.75]
        inward_north = [mid + 1.0, ROOM_H - 1.75]
        side_a, side_b = (
            {"room": south["id"], "tiles": tiles_south, "inward": inward_south},
            {"room": north["id"], "tiles": tiles_north, "inward": inward_north},
        )
    else:
        west, east = (room_a, room_b) if room_a["gx"] < room_b["gx"] else (room_b, room_a)
        mid = ROOM_H // 2 - 1
        tiles_west = [[ROOM_W - 1, mid], [ROOM_W - 1, mid + 1]]
        tiles_east = [[0, mid], [0, mid + 1]]
        inward_west = [ROOM_W - 1.75, mid + 1.0]
        inward_east = [1.75, mid + 1.0]
        side_a, side_b = (
            {"room": west["id"], "tiles": tiles_west, "inward": inward_west},
            {"room": east["id"], "tiles": tiles_east, "inward": inward_east},
        )
    char = "D" if locked else "d"
    for side in (side_a, side_b):
        room = rooms[side["room"]]
        for x, y in side["tiles"]:
            _set(room, x, y, char)
    _remember_link(rooms, side_a["room"], side_b["room"])
    doors.append({"id": door_id, "a": side_a, "b": side_b, "locked": locked, "open": not locked})


def _lock_doors(rooms: dict, doors: list, cell_id: str, chance: float, rng: random.Random) -> None:
    for door in doors:
        touches_cell = door["a"]["room"] == cell_id or door["b"]["room"] == cell_id
        locked = (not touches_cell) and rng.random() < chance
        door["locked"] = locked
        door["open"] = not locked
        char = "D" if locked else "d"
        for side in (door["a"], door["b"]):
            room = rooms[side["room"]]
            for x, y in side["tiles"]:
                _set(room, x, y, char)


def _add_stairs(rooms: dict, floors: int, rng: random.Random) -> None:
    for floor in range(floors - 1):
        lower = _pick_room(rooms, floor, rng, avoid_cell=True)
        upper = _pick_room(rooms, floor + 1, rng, avoid_cell=False)
        lx, ly = _open_center(lower)
        ux, uy = _open_center(upper)
        _set(lower, lx, ly, "u")
        _set(upper, ux, uy, "n")
        lower["up"] = {"room": upper["id"], "x": ux + 0.5, "y": uy + 0.5}
        upper["down"] = {"room": lower["id"], "x": lx + 0.5, "y": ly + 0.5}


def _place_exit(rooms: dict, floors: int) -> None:
    top = [room for room in rooms.values() if room["floor"] == floors - 1]
    stairs_down = next(room["id"] for room in top if room["down"])
    distances = _distances(rooms, stairs_down)
    goal = max(top, key=lambda room: (distances.get(room["id"], 0), room["gx"], -room["gy"]))
    x, y = _open_center(goal)
    # Keep the stair tile if the center was already used.
    if _get(goal, x, y) != ".":
        x, y = _first_dot(goal)
    _set(goal, x, y, "e")
    goal["exit"] = True


def _plans_room(rooms: dict, floors: int) -> str:
    top = [room for room in rooms.values() if room["floor"] == floors - 1 and not room["exit"]]
    if not top:
        top = [room for room in rooms.values() if room["floor"] == floors - 1]
    cell = next(room["id"] for room in rooms.values() if room["cell"])
    distances = _distances(rooms, cell)
    picked = max(top, key=lambda room: (distances.get(room["id"], 0), room["id"]))
    return picked["id"]


def _place_plans(room: dict, rng: random.Random, nid) -> int:
    spot = _spot(room, rng, gap=1.2) or (ROOM_W / 2, ROOM_H / 2)
    chest = {
        "id": nid(),
        "x": spot[0],
        "y": spot[1],
        "locked": True,
        "open": False,
        "progress": 0.0,
        "need": round(rng.uniform(6.0, 9.0), 2),
        "explosive": False,
        "contents": [{"kind": "plans", "amount": 1}],
    }
    room["chests"].append(chest)
    return chest["id"]


def _populate(room: dict, spec: dict, rank: int, rng: random.Random, nid) -> None:
    if room["cell"]:
        _add_guard(room, "guard", rank, rng, nid, cell=True)
    else:
        count = 0
        if rng.random() < 0.5 + rank * 0.04:
            count = 1
        if count and rng.random() < 0.18 + rank * 0.04:
            count = 2
        if room["exit"]:
            count = max(1, count)
        for _ in range(count):
            kind = "ss" if rng.random() < spec["ss"] else "guard"
            _add_guard(room, kind, rank, rng, nid, cell=False)
    if room["cell"]:
        return
    extras = 1 if rng.random() < 0.62 else 0
    if extras and rng.random() < 0.22:
        extras = 2
    for _ in range(extras):
        spot = _spot(room, rng, gap=1.3)
        if not spot:
            return
        room["chests"].append(_mundane_chest(nid(), spot, rank, rng))


def _add_guard(room: dict, kind: str, rank: int, rng: random.Random, nid, cell: bool) -> None:
    if cell:
        x, y = 2.6, 2.35
        other_x = ROOM_W - 2.6
        patrol = [[2.6, 2.35], [other_x, 2.35]]
        facing = 0.0
    else:
        spot = _spot(room, rng, gap=1.4)
        if not spot:
            return
        x, y = spot
        other = _spot(room, rng, gap=1.2) or spot
        patrol = [[x, y], [other[0], other[1]]]
        facing = math.atan2((ROOM_H / 2) - y, (ROOM_W / 2) - x)
    loot = []
    if rng.random() < 0.7:
        loot.append({"kind": "bullets", "amount": rng.randint(1, 4)})
    if rng.random() < 0.16:
        loot.append({"kind": "grenade", "amount": 1})
    if rng.random() < 0.34:
        loot.append({"kind": "key", "amount": 1})
    room["guards"].append(
        {
            "id": nid(),
            "x": x,
            "y": y,
            "home": [x, y],
            "kind": kind,
            "hp": 5 if kind == "ss" else 2,
            "max_hp": 5 if kind == "ss" else 2,
            "facing": facing,
            "home_facing": facing,
            "state": "patrol",
            "patrol": patrol,
            "pi": 0,
            "stuck": 0.0,
            "cooldown": rng.uniform(0.2, 0.8),
            "surrender_t": 0.0,
            "giveup": 0.28 + rank * 0.06 + rng.random() * 0.45,
            "alert_for": 0.0,
            "searched": False,
            "loot": loot,
            "said_halt": False,
            "said_give": False,
            "said_ss": False,
        }
    )


def _mundane_chest(cid: int, spot: tuple[float, float], rank: int, rng: random.Random) -> dict:
    roll = rng.random()
    if roll < 0.34:
        contents = [{"kind": "bullets", "amount": rng.randint(2, 5)}]
    elif roll < 0.48:
        contents = [{"kind": "grenade", "amount": 1}]
    elif roll < 0.62:
        contents = [{"kind": "key", "amount": 1}]
    elif roll < 0.74:
        contents = [{"kind": "sausage", "amount": 1}]
    elif roll < 0.86:
        contents = [{"kind": "sauerkraut", "amount": 1}]
    else:
        contents = [{"kind": "schnapps", "amount": 1}]
    return {
        "id": cid,
        "x": spot[0],
        "y": spot[1],
        "locked": True,
        "open": False,
        "progress": 0.0,
        "need": round(rng.uniform(4.0, 7.5) + rank * 0.4, 2),
        "explosive": False,
        "contents": contents,
    }


def _guarantee_gear(rooms: dict, rng: random.Random) -> None:
    chests = [
        chest
        for room in _rooms_in_order(rooms)
        if not room["cell"]
        for chest in room["chests"]
        if not any(item["kind"] == "plans" for item in chest["contents"])
    ]
    if len(chests) < 2:
        return
    rng.shuffle(chests)
    chests[0]["contents"] = [{"kind": "uniform", "amount": 1}]
    chests[0]["explosive"] = False
    chests[1]["contents"] = [{"kind": "vest", "amount": 1}]
    chests[1]["explosive"] = False
    for chest in chests[2:]:
        mundane = not any(item["kind"] in {"uniform", "vest", "plans"} for item in chest["contents"])
        if mundane and rng.random() < 0.1:
            chest["explosive"] = True


def _sprinkle_keys(rooms: dict, doors: list, rng: random.Random) -> None:
    locked = sum(1 for door in doors if door["locked"])
    have = 0
    for room in rooms.values():
        for guard in room["guards"]:
            have += sum(item["amount"] for item in guard["loot"] if item["kind"] == "key")
        for chest in room["chests"]:
            have += sum(item["amount"] for item in chest["contents"] if item["kind"] == "key")
    need = max(0, min(locked, 3) - have)
    guards = [guard for room in _rooms_in_order(rooms) if not room["cell"] for guard in room["guards"]]
    rng.shuffle(guards)
    for guard in guards[:need]:
        guard["loot"].append({"kind": "key", "amount": 1})


def _obstacles(room: dict, rng: random.Random) -> None:
    if room["cell"]:
        return
    targets = _interesting_tiles(room)
    placed = 0
    for _ in range(10):
        if placed >= 2:
            return
        x = rng.randrange(2, ROOM_W - 2)
        y = rng.randrange(2, ROOM_H - 2)
        if _get(room, x, y) != ".":
            continue
        if _near_special(room, x, y):
            continue
        _set(room, x, y, "#")
        if not _can_reach(room, targets):
            _set(room, x, y, ".")
            continue
        placed += 1


def _interesting_tiles(room: dict) -> list[tuple[int, int]]:
    found = []
    for y in range(room["h"]):
        for x in range(room["w"]):
            if _get(room, x, y) in {"d", "D", "u", "n", "e"}:
                found.append((x, y))
    return found


def _near_special(room: dict, x: int, y: int) -> bool:
    for yy in range(max(0, y - 2), min(room["h"], y + 3)):
        for xx in range(max(0, x - 2), min(room["w"], x + 3)):
            if _get(room, xx, yy) in {"d", "D", "u", "n", "e"}:
                return True
    return False


def _can_reach(room: dict, targets: list[tuple[int, int]]) -> bool:
    if not targets:
        return True
    start = targets[0]
    seen = {start}
    queue = [start]
    while queue:
        x, y = queue.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in seen:
                continue
            tile = _get(room, nx, ny)
            if tile == "#":
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    return all(tile in seen for tile in targets)


def _spot(room: dict, rng: random.Random, gap: float) -> tuple[float, float] | None:
    taken = [(chest["x"], chest["y"]) for chest in room["chests"]]
    taken += [(guard["x"], guard["y"]) for guard in room["guards"]]
    options = []
    for y in range(2, room["h"] - 2):
        for x in range(2, room["w"] - 2):
            if _get(room, x, y) != ".":
                continue
            cx, cy = x + 0.5, y + 0.5
            if any(math.hypot(cx - tx, cy - ty) < gap for tx, ty in taken):
                continue
            options.append((cx, cy))
    if not options:
        return None
    return rng.choice(options)


def _open_center(room: dict) -> tuple[int, int]:
    x, y = ROOM_W // 2, ROOM_H // 2
    if _get(room, x, y) == ".":
        return x, y
    found = _first_dot(room)
    return found


def _first_dot(room: dict) -> tuple[int, int]:
    for y in range(1, room["h"] - 1):
        for x in range(1, room["w"] - 1):
            if _get(room, x, y) == ".":
                return x, y
    return ROOM_W // 2, ROOM_H // 2


def _pick_room(rooms: dict, floor: int, rng: random.Random, avoid_cell: bool) -> dict:
    choices = [
        room
        for room in _rooms_in_order(rooms)
        if room["floor"] == floor and not (avoid_cell and room["cell"]) and room["up"] is None and room["down"] is None
    ]
    if not choices:
        choices = [room for room in rooms.values() if room["floor"] == floor]
    return rng.choice(choices)


def _rooms_in_order(rooms: dict) -> list[dict]:
    return sorted(rooms.values(), key=lambda room: (room["floor"], room["gy"], room["gx"]))


def _spawn_point(room: dict) -> tuple[float, float]:
    x, y = 2.4, ROOM_H - 2.5
    if _get(room, int(x), int(y)) == ".":
        return x, y
    tx, ty = _first_dot(room)
    return tx + 0.5, ty + 0.5


def _walk(links: dict[str, set[str]], start: str) -> dict[str, int]:
    dist = {start: 0}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for nxt in sorted(links[current]):
            if nxt in dist:
                continue
            dist[nxt] = dist[current] + 1
            queue.append(nxt)
    return dist


def _get(room: dict, x: int, y: int) -> str:
    if x < 0 or y < 0 or x >= room["w"] or y >= room["h"]:
        return "#"
    return room["tiles"][y * room["w"] + x]


def _set(room: dict, x: int, y: int, char: str) -> None:
    i = y * room["w"] + x
    tiles = room["tiles"]
    room["tiles"] = tiles[:i] + char + tiles[i + 1 :]


def _remember_link(rooms: dict, id_a: str, id_b: str) -> None:
    rooms[id_a].setdefault("links", [])
    rooms[id_b].setdefault("links", [])
    if id_b not in rooms[id_a]["links"]:
        rooms[id_a]["links"].append(id_b)
    if id_a not in rooms[id_b]["links"]:
        rooms[id_b]["links"].append(id_a)


def _distances(rooms: dict, start: str) -> dict[str, int]:
    links: dict[str, set[str]] = {room_id: set(room.get("links") or []) for room_id, room in rooms.items()}
    for room in rooms.values():
        if room["up"]:
            links[room["id"]].add(room["up"]["room"])
        if room["down"]:
            links[room["id"]].add(room["down"]["room"])
    return _walk(links, start)
