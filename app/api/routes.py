"""Players, castles, and the live play socket.

The phone is a remote screen. Ranks, loot, and deaths live in SQLite on
the machine that runs this process.
"""

from __future__ import annotations

import json
import random
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.castle import RANKS, generate_castle, rank_name
from app.database import SessionLocal, get_db
from app.game import continue_after_death, dump_state, public_view, step
from app.models import Player, Run, utcnow

router = APIRouter(prefix="/api")


class PlayerIn(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class PlayerPatch(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class RunIn(BaseModel):
    player_id: int
    rank: int | None = None
    fresh: bool = False


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise HTTPException(status_code=400, detail="Enter a name.")
    return cleaned[:24]


def _player(db: Session, player_id: int) -> Player:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="No such player.")
    return player


def _run_for(db: Session, run_id: int, player_id: int) -> tuple[Run, Player]:
    run = db.get(Run, run_id)
    if run is None or run.player_id != player_id:
        raise HTTPException(status_code=404, detail="No such castle.")
    player = _player(db, player_id)
    return run, player


def _load(run: Run) -> dict:
    return json.loads(run.state_json)


def _save(db: Session, run: Run, state: dict) -> None:
    run.state_json = dump_state(state)
    run.status = state["status"]
    run.seed = int(state["seed"])
    run.updated_at = utcnow()
    db.commit()


def _summary(run: Run) -> dict:
    state = _load(run)
    room = state["rooms"][state["player"]["room"]]
    return {
        "id": run.id,
        "status": state["status"],
        "rank": run.rank,
        "rank_name": rank_name(run.rank),
        "floor_name": public_view(state)["floor_name"],
        "plans": bool(state["player"]["plans"]),
        "time": int(state.get("time", 0)),
        "room": room["id"],
    }


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/players")
def list_players(db: Session = Depends(get_db)) -> list[dict]:
    players = db.scalars(select(Player).order_by(Player.created_at, Player.id)).all()
    return [_player_out(player) for player in players]


@router.post("/players", status_code=201)
def create_player(body: PlayerIn, db: Session = Depends(get_db)) -> dict:
    name = _clean_name(body.name)
    taken = db.scalar(select(Player).where(func.lower(Player.name) == name.casefold()))
    if taken is not None:
        raise HTTPException(status_code=409, detail="That name is already on this machine.")
    player = Player(name=name)
    db.add(player)
    db.commit()
    db.refresh(player)
    return _player_out(player)


@router.patch("/players/{player_id}")
def rename_player(player_id: int, body: PlayerPatch, db: Session = Depends(get_db)) -> dict:
    player = _player(db, player_id)
    name = _clean_name(body.name)
    taken = db.scalar(select(Player).where(func.lower(Player.name) == name.casefold(), Player.id != player.id))
    if taken is not None:
        raise HTTPException(status_code=409, detail="That name is already on this machine.")
    player.name = name
    db.commit()
    return _player_out(player)


@router.delete("/players/{player_id}")
def delete_player(player_id: int, db: Session = Depends(get_db)) -> dict:
    player = _player(db, player_id)
    for old in db.scalars(select(Run).where(Run.player_id == player.id)).all():
        db.delete(old)
    db.delete(player)
    db.commit()
    return {"ok": True}


@router.get("/home")
def home(player_id: int, db: Session = Depends(get_db)) -> dict:
    player = _player(db, player_id)
    active = db.scalar(
        select(Run)
        .where(Run.player_id == player.id, Run.status.in_(("playing", "dead")))
        .order_by(Run.updated_at.desc())
    )
    return {
        "player": _player_out(player),
        "ranks": [{"rank": index, "name": spec["name"], "open": index <= player.rank} for index, spec in enumerate(RANKS)],
        "active": _summary(active) if active else None,
    }


@router.post("/runs", status_code=201)
def start_run(body: RunIn, db: Session = Depends(get_db)) -> dict:
    player = _player(db, body.player_id)
    if not body.fresh:
        active = db.scalar(
            select(Run)
            .where(Run.player_id == player.id, Run.status.in_(("playing", "dead")))
            .order_by(Run.updated_at.desc())
        )
        if active is not None:
            return {"run": _summary(active), "view": public_view(_load(active)), "resumed": True}
    rank = player.rank if body.rank is None else int(body.rank)
    if rank < 0 or rank > player.rank or rank >= len(RANKS):
        raise HTTPException(status_code=400, detail="That rank is not open.")
    for old in db.scalars(select(Run).where(Run.player_id == player.id, Run.status.in_(("playing", "dead")))).all():
        old.status = "abandoned"
    seed = random_seed()
    state = generate_castle(rank, seed)
    run = Run(player_id=player.id, rank=rank, seed=state["seed"], state_json=dump_state(state), status="playing")
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"run": _summary(run), "view": public_view(state), "resumed": False}


@router.get("/runs/{run_id}")
def get_run(run_id: int, player_id: int, db: Session = Depends(get_db)) -> dict:
    run, _player_row = _run_for(db, run_id, player_id)
    return {"run": _summary(run), "view": public_view(_load(run))}


@router.post("/runs/{run_id}/continue")
def continue_run(run_id: int, player_id: int, db: Session = Depends(get_db)) -> dict:
    run, player = _run_for(db, run_id, player_id)
    state = _load(run)
    if state.get("status") != "dead":
        raise HTTPException(status_code=409, detail="You are not down.")
    player.deaths += 1
    state = continue_after_death(state)
    run.rank = int(state["rank"])
    _save(db, run, state)
    return {"run": _summary(run), "view": public_view(state)}


@router.post("/runs/{run_id}/resolve")
def resolve_run(run_id: int, player_id: int, db: Session = Depends(get_db)) -> dict:
    run, player = _run_for(db, run_id, player_id)
    state = _load(run)
    if state.get("status") != "escaped":
        raise HTTPException(status_code=409, detail="You have not left the castle.")
    plans = bool(state["player"]["plans"])
    promoted = False
    player.escapes += 1
    if plans:
        player.escapes_with_plans += 1
        if run.rank == player.rank and player.rank < len(RANKS) - 1:
            player.rank += 1
            promoted = True
    run.status = "escaped"
    state["status"] = "escaped"
    _save(db, run, state)
    return {"promoted": promoted, "rank": player.rank, "rank_name": rank_name(player.rank), "plans": plans}


@router.get("/admin/summary")
def admin_summary(db: Session = Depends(get_db)) -> dict:
    return {
        "players": db.scalar(select(func.count()).select_from(Player)) or 0,
        "runs": db.scalar(select(func.count()).select_from(Run)) or 0,
        "escapes": db.scalar(select(func.coalesce(func.sum(Player.escapes), 0))) or 0,
    }


@router.websocket("/runs/{run_id}/play")
async def play(websocket: WebSocket, run_id: int, player_id: int) -> None:
    await websocket.accept()
    db = SessionLocal()
    run = None
    state = None
    try:
        run = db.get(Run, run_id)
        if run is None or run.player_id != player_id:
            await websocket.close(code=4404)
            return
        state = _load(run)
        await websocket.send_json(public_view(state))
        last = time.monotonic()
        last_save = last
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("cmd") == "reload":
                db.refresh(run)
                state = _load(run)
            elif state.get("status") == "playing":
                now = time.monotonic()
                step(state, msg, min(0.2, now - last))
                last = now
                if now - last_save > 0.7 or state.get("status") != "playing":
                    _save(db, run, state)
                    last_save = now
            await websocket.send_json(public_view(state))
    except WebSocketDisconnect:
        pass
    finally:
        try:
            if run is not None and state is not None:
                _save(db, run, state)
        except Exception:
            db.rollback()
        db.close()


def _player_out(player: Player) -> dict:
    return {
        "id": player.id,
        "name": player.name,
        "rank": player.rank,
        "rank_name": rank_name(player.rank),
        "escapes": player.escapes,
        "escapes_with_plans": player.escapes_with_plans,
        "deaths": player.deaths,
    }


def random_seed() -> int:
    return random.SystemRandom().randrange(1, 2**31 - 1)
