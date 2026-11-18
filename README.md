# Feldstein

A phone homage to [Castle Wolfenstein](https://en.wikipedia.org/wiki/Castle_Wolfenstein) (Muse Software, 1981). You wake in the dungeon with a pistol and three grenades. Find the war plans, then leave by the rampart gate.

It is a fan-made home version. It is not the original game, and it is not affiliated with Muse Software or the later Wolfenstein games. The rooms, pictures, and barks are drawn for this page. Nothing is loaded from the 1981 disks.

Built the same way as [Meow](https://github.com/nibrocsolutions/meow): one Python container, SQLite on a Docker volume, and a page served by that same container. The castle rules run on the server. The phone is a screen and a pair of sticks.

Feldstein listens on **port 8096**.

## Quick start

```bash
git clone <this repo>
cd castle
docker compose up -d --build
```

On the phone, join the same Wi-Fi as the machine and open `http://<host-ip>:8096`.

Add it to the home screen (Safari: Share → Add to Home Screen, Chrome: menu → Add to Home screen) and it opens like an app.

### Useful commands

```bash
docker compose logs -f
git pull && docker compose up -d --build
docker compose down
```

`docker compose down` keeps the `feldstein-data` volume. Add `-v` only when you mean to erase the players and the castles.

## What you can do

- Pick a name. The phone remembers it. Each name has its own rank and record.
- Walk a castle that is generated on the server from a seed. A Private starts in a 12-room castle. A Colonel gets 60 rooms, which is about the size of the 1981 castle. A General gets 80.
- Sneak. An ordinary sentry facing the other way does not see you. A stolen coat fools ordinary sentries while your pistol is holstered. Storm guards wear pale vests and are not fooled.
- Hold a drawn pistol on an ordinary sentry and he gives up (`Kamerad`). Search him. Storm guards do not give up. A grenade is the sure way through a vest.
- Pick locks by holding Use. Shooting a chest hurries the lock and wakes the room. Some chests are packed with explosives. Shooting one of those, or standing in your own blast, brings the wing down and draws a new castle at the same rank.
- Carry at most ten rounds and three grenades. Keys open doors. You can also shoot a lock off a door.
- Bumping a wall stuns you for a moment.
- Bring the plans out through the rampart gate and Allied command promotes you. The next castle is harder. Escaping without the plans does not.
- If you are shot, you wake in the same castle: sentries are back on their posts, chests are shut, and doors you already broke stay open. The layout is kept, the way the original kept a castle on disk until a blast or a new game replaced it.

There are eight ranks: Private, Corporal, Sergeant, Lieutenant, Captain, Major, Colonel, General. You can draw a new castle at your rank or any lower rank. Only escaping your current rank with the plans promotes you.

## Controls

- Left stick moves. Right stick aims. Fire shoots along the aim, or along your walk if you are not aiming.
- Use searches a surrendered or fallen sentry, spends a key on a locked door, or keeps picking a chest while you hold it.
- Draw holsters the pistol. Bomb throws a grenade.
- Keyboard: WASD to move, arrows to aim, J or Space to fire, E to use, G for a grenade, H to holster.

Lockpicking is shorter than on the Apple II. Contemporary reviews called the original chest timer the worst part of the game, so a lock here is a few seconds, not a few minutes. Shooting it is still a risk.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
mkdir -p data
DATA_DIR=./data uvicorn app.main:app --reload --host 0.0.0.0 --port 8096
```

Tests:

```bash
pytest
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Health check |
| GET, POST | `/api/players` | Names on this machine |
| PATCH, DELETE | `/api/players/{id}` | Rename or remove a player |
| GET | `/api/home?player_id=` | Rank, record, and the castle in progress |
| POST | `/api/runs` | Resume, or draw a castle (`fresh`, optional `rank`) |
| GET | `/api/runs/{id}?player_id=` | The current room, without hidden chest contents |
| POST | `/api/runs/{id}/continue?player_id=` | Wake after a death |
| POST | `/api/runs/{id}/resolve?player_id=` | Report an escape and maybe promote |
| GET | `/api/admin/summary` | Player and escape counts |
| WebSocket | `/api/runs/{id}/play?player_id=` | Sticks and buttons in, room state out |

The socket expects JSON: `move` and `aim` are each `[x, y]` from -1 to 1, `pressed` is a list of `fire`, `grenade`, `use`, `holster`, and `use` is true while the Use button is held. Send about ten to twenty times a second. The server steps the current room by the time since the last message. Other rooms stay as you left them.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATA_DIR` | `./data` locally, `/data` in Docker | SQLite directory |
| `PORT` | `8096` | HTTP port |
| `DATABASE_URL` | `sqlite:///{DATA_DIR}/feldstein.db` | Override the database |
| `TZ` | `America/New_York` in Docker | Clock inside the container |

## Notes

- Anyone who can open the address can play, and anyone who can open `/api/admin/summary` can read the counts. Keep it on your home network. Do not forward port 8096 to the internet.
- The phone has to reach the machine. On the same Wi-Fi, use that machine's address.
- Progress lives in SQLite. The phone only remembers the player id and whether German barks are spoken.
- The page does not load fonts, pictures, or castles from the internet. After the container is built, a round can be played with the machine offline. Barks use the phone's own German voice, if it has one. The words are also printed on the room.
- The image is the multi-arch `python:3.12-slim` image, so it runs on a 64-bit Raspberry Pi and on a normal PC.

## What this was built from

The 1981 game is a top-down stealth escape: one room on screen, patrolling sentries, locked chests, a uniform, a vest, ten bullets, three grenades, and a castle of about sixty rooms generated at the start and kept until you blow it up. Silas Warner named eight German barks in the manual, including Halt, Kamerad, and Schweinhund. A longplay of the Apple II original is at <https://www.youtube.com/watch?v=8fgok9eHqO8>. Hardcore Gaming 101 and the [Wikipedia article](https://en.wikipedia.org/wiki/Castle_Wolfenstein) are the other sources for the rules.

There is no maintained open-source clone of that 1981 game worth building on. The Wolfenstein repositories on GitHub are the 1992 first-person shooter or Return to Castle Wolfenstein. Those are a different game, and their data files are not free to redistribute. [castlehondenstein](https://github.com/seeseemelk/castlehondenstein) is a two-commit Love2D sketch, not a castle. This project is a new simulation of the 1981 rules.

## Project layout

```
├── Dockerfile
├── docker-compose.yml
├── app/
│   ├── main.py
│   ├── castle.py
│   ├── game.py
│   ├── api/routes.py
│   └── static/
└── tests/
```
