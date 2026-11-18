const app = document.querySelector("#app");
const PLAYER_KEY = "feldstein-player";
const VOICE_KEY = "feldstein-voice";
const BARKS = new Set(["Halt!", "Kamerad!", "Schweinhund!", "Mein Leben!"]);

let playerId = null;
let home = null;
let screen = "boot";
let runId = null;
let chosenRank = null;
let voiceOn = localStorage.getItem(VOICE_KEY) !== "0";
let ws = null;
let socketGen = 0;
let snaps = [];
let spokenSeq = -1;
let useHeld = false;
let stickMove = [0, 0];
let stickAim = [0, 0];
const keys = new Set();
let pending = [];
let audioCtx = null;
let loopStarted = false;

function esc(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : "The castle did not answer.");
  }
  return body;
}

document.addEventListener("keydown", (event) => {
  if (screen !== "play") return;
  const once = { KeyJ: "fire", Space: "fire", KeyG: "grenade", KeyE: "use", KeyH: "holster" };
  if (once[event.code]) {
    event.preventDefault();
    if (!event.repeat) {
      pending.push(once[event.code]);
      if (event.code === "KeyE") useHeld = true;
      send();
    }
  }
  keys.add(event.code);
});

document.addEventListener("keyup", (event) => {
  keys.delete(event.code);
  if (event.code === "KeyE") useHeld = false;
});

document.addEventListener("touchmove", (event) => {
  if (screen === "play") event.preventDefault();
}, { passive: false });

function axis(negative, positive) {
  const x = (keys.has(positive) ? 1 : 0) - (keys.has(negative) ? 1 : 0);
  return x;
}

function composeInput() {
  let mx = stickMove[0];
  let my = stickMove[1];
  if (Math.hypot(mx, my) < 0.18) {
    mx = axis("KeyA", "KeyD");
    my = axis("KeyW", "KeyS");
  }
  let ax = stickAim[0];
  let ay = stickAim[1];
  if (Math.hypot(ax, ay) < 0.18) {
    ax = axis("ArrowLeft", "ArrowRight");
    ay = axis("ArrowUp", "ArrowDown");
  }
  const pressed = pending.splice(0, pending.length);
  return {
    cmd: "input",
    move: [mx, my],
    aim: [ax, ay],
    pressed,
    use: useHeld || keys.has("KeyE"),
  };
}

function send() {
  if (!ws || ws.readyState !== 1 || screen !== "play") return;
  ws.send(JSON.stringify(composeInput()));
}

setInterval(send, 80);

function speak(text) {
  if (!voiceOn || !BARKS.has(text) || !window.speechSynthesis) return;
  const utterance = new SpeechSynthesisUtterance(text.replace("!", ""));
  utterance.lang = "de-DE";
  utterance.rate = 0.95;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

function tone(freq, duration, type, gain) {
  try {
    if (!audioCtx) audioCtx = new AudioContext();
    const oscillator = audioCtx.createOscillator();
    const amp = audioCtx.createGain();
    oscillator.type = type;
    oscillator.frequency.value = freq;
    amp.gain.value = gain;
    oscillator.connect(amp);
    amp.connect(audioCtx.destination);
    oscillator.start();
    amp.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
    oscillator.stop(audioCtx.currentTime + duration);
  } catch (_error) {
    /* The room still plays with the speaker off. */
  }
}

function noteSounds(previous, view) {
  if (!previous || previous.room_id !== view.room_id) return;
  if (view.player.bullets < previous.player.bullets) tone(540, 0.06, "square", 0.04);
  if (view.player.grenades < previous.player.grenades) tone(140, 0.2, "sawtooth", 0.05);
  if (view.blasts.length > previous.blasts.length) tone(70, 0.28, "triangle", 0.06);
  if (previous.player.stun === 0 && view.player.stun > 0) tone(880, 0.12, "square", 0.03);
}

async function boot() {
  const saved = localStorage.getItem(PLAYER_KEY);
  if (saved) {
    try {
      playerId = saved;
      home = await api(`/api/home?player_id=${saved}`);
      chosenRank = home.player.rank;
      renderHome();
      return;
    } catch (_error) {
      localStorage.removeItem(PLAYER_KEY);
      playerId = null;
    }
  }
  renderName();
}

function renderName() {
  screen = "home";
  app.innerHTML = `
    <main class="home gate">
      <h1>FELDSTEIN</h1>
      <p class="lede">A phone homage to Castle Wolfenstein, the 1981 castle escape. Find the war plans, then leave by the rampart gate.</p>
      <form class="card stack" id="join">
        <label for="name">Your name on this machine</label>
        <input id="name" name="name" maxlength="24" autocomplete="nickname" required>
        <p class="error" id="err"></p>
        <button class="primary" type="submit">Take the pistol</button>
      </form>
    </main>`;
  app.querySelector("#join").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = app.querySelector("#name").value;
    try {
      const player = await api("/api/players", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      localStorage.setItem(PLAYER_KEY, String(player.id));
      playerId = String(player.id);
      home = await api(`/api/home?player_id=${player.id}`);
      chosenRank = 0;
      renderHome();
    } catch (error) {
      app.querySelector("#err").textContent = error.message;
    }
  });
}

function renderHome() {
  screen = "home";
  closeSocket();
  const player = home.player;
  const active = home.active;
  const rankButtons = home.ranks.map((rank) => {
    const disabled = rank.open ? "" : "disabled";
    const on = rank.rank === chosenRank ? "on" : "";
    return `<button type="button" class="${on}" data-rank="${rank.rank}" ${disabled}>${esc(rank.name)}</button>`;
  }).join("");
  app.innerHTML = `
    <main class="home">
      <h1>FELDSTEIN</h1>
      <p class="lede">${esc(player.name)}, ${esc(player.rank_name)}. Steal the plans and get out of the castle.</p>
      <section class="stats">
        <div><strong>${player.escapes}</strong><span>Escapes</span></div>
        <div><strong>${player.escapes_with_plans}</strong><span>With plans</span></div>
        <div><strong>${player.deaths}</strong><span>Deaths</span></div>
      </section>
      <div class="stack card">
        ${active ? `<button class="primary" type="button" id="resume">Continue · ${esc(active.floor_name)}</button>` : ""}
        <button class="${active ? "" : "primary"}" type="button" id="fresh">${active ? "Abandon it and draw a new castle" : "Enter the castle"}</button>
        <div class="ranks sans" id="ranks">${rankButtons}</div>
        <p class="error" id="err"></p>
      </div>
      <section class="card how">
        <p>Ordinary sentries give up when you hold a pistol on them. Storm guards wear pale vests and do not. A coat from a chest fools the ordinary ones until you draw.</p>
        <p>Use searches a body, spends a key, or keeps picking a lock while held. Shooting a chest hurries the lock and wakes the room. Some chests are explosives.</p>
        <p>You carry ten rounds and three grenades. Bumping a wall stuns you. The left stick moves, the right stick aims.</p>
        <p>Keyboard: WASD, arrow keys, J to fire, E to use, G for a grenade, H to holster.</p>
      </section>
      <div class="row">
        <button class="quiet" type="button" id="voice">${voiceOn ? "German voices on" : "German voices off"}</button>
        <button class="quiet" type="button" id="forget">Forget this name</button>
      </div>
      <p class="lede">Not the 1981 game, and not affiliated with Muse Software or the later Wolfenstein games. The pictures and the words are new. The castle is built on this machine.</p>
    </main>`;
  app.querySelectorAll("[data-rank]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      chosenRank = Number(button.dataset.rank);
      renderHome();
    });
  });
  const resume = app.querySelector("#resume");
  if (resume) resume.addEventListener("click", () => showPlay(active.id));
  app.querySelector("#fresh").addEventListener("click", async () => {
    try {
      const body = { player_id: Number(playerId), fresh: true, rank: chosenRank };
      const result = await api("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      showPlay(result.run.id);
    } catch (error) {
      app.querySelector("#err").textContent = error.message;
    }
  });
  app.querySelector("#voice").addEventListener("click", () => {
    voiceOn = !voiceOn;
    localStorage.setItem(VOICE_KEY, voiceOn ? "1" : "0");
    renderHome();
  });
  app.querySelector("#forget").addEventListener("click", () => {
    localStorage.removeItem(PLAYER_KEY);
    playerId = null;
    renderName();
  });
}

function showPlay(id) {
  screen = "play";
  runId = id;
  snaps = [];
  spokenSeq = -1;
  useHeld = false;
  stickMove = [0, 0];
  stickAim = [0, 0];
  document.body.classList.add("playing");
  app.innerHTML = `
    <section class="play">
      <header class="hud">
        <div class="hud-main">
          <div class="floor" id="floor">Castle</div>
          <div class="ammo" id="ammo"></div>
          <div class="pills" id="pills"></div>
        </div>
        <div class="hud-side">
          <div class="minimap" id="map"></div>
          <div class="hud-buttons">
            <button type="button" id="help">Help</button>
            <button type="button" id="leave">Leave</button>
          </div>
        </div>
      </header>
      <div class="stage">
        <canvas id="room"></canvas>
        <div class="log" id="log"></div>
        <div class="veil hidden" id="veil"></div>
      </div>
      <div class="deck">
        <div class="stick" id="move"><div class="knob"></div><span>Move</span></div>
        <div class="actions">
          <button type="button" id="fire">Fire</button>
          <button type="button" id="gun">Draw</button>
          <button type="button" id="use">Use</button>
          <button type="button" id="bomb">Bomb</button>
          <div class="stick aim" id="aim"><div class="knob"></div><span>Aim</span></div>
        </div>
      </div>
    </section>`;
  bindStick(app.querySelector("#move"), (value) => { stickMove = value; });
  bindStick(app.querySelector("#aim"), (value) => { stickAim = value; });
  bindTap(app.querySelector("#fire"), "fire");
  bindTap(app.querySelector("#bomb"), "grenade");
  bindTap(app.querySelector("#gun"), "holster");
  bindHold(app.querySelector("#use"));
  app.querySelector("#leave").addEventListener("click", () => {
    document.body.classList.remove("playing");
    boot();
  });
  app.querySelector("#help").addEventListener("click", () => {
    const veil = app.querySelector("#veil");
    veil.classList.remove("hidden");
    veil.innerHTML = `
      <div class="sheet">
        <h2>In the room</h2>
        <p>Move with the left stick. Aim with the right. Fire shoots that way, or the way you are walking if you are not aiming. Hold Use to pick a lock. Tap Use to search a surrendered or fallen sentry, or to spend a key.</p>
        <p>Holster the pistol before you walk past a sentry in a stolen coat. Storm guards ignore the coat. A grenade is the sure way through a vest.</p>
        <button type="button" id="close-help">Back to the room</button>
      </div>`;
    veil.querySelector("#close-help").addEventListener("click", () => {
      if (latestStatus() === "playing") veil.classList.add("hidden");
      else paintVeil(snaps.length ? snaps[snaps.length - 1].view : null);
    });
  });
  connect(id);
  if (!loopStarted) {
    loopStarted = true;
    requestAnimationFrame(frame);
  }
}

function latestStatus() {
  return snaps.length ? snaps[snaps.length - 1].view.status : "playing";
}

function bindStick(el, onChange) {
  const knob = el.querySelector(".knob");
  let pointer = null;
  function place(clientX, clientY) {
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    let dx = clientX - cx;
    let dy = clientY - cy;
    const max = rect.width * 0.32;
    const mag = Math.hypot(dx, dy) || 1;
    const clamped = Math.min(mag, max);
    dx = (dx / mag) * clamped;
    dy = (dy / mag) * clamped;
    knob.style.transform = `translate(${dx}px, ${dy}px)`;
    onChange([dx / max, dy / max]);
  }
  function end(event) {
    if (event.pointerId !== pointer) return;
    pointer = null;
    knob.style.transform = "translate(0px, 0px)";
    onChange([0, 0]);
  }
  el.addEventListener("pointerdown", (event) => {
    pointer = event.pointerId;
    el.setPointerCapture(pointer);
    place(event.clientX, event.clientY);
    event.preventDefault();
  });
  el.addEventListener("pointermove", (event) => {
    if (event.pointerId === pointer) place(event.clientX, event.clientY);
  });
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("contextmenu", (event) => event.preventDefault());
}

function bindTap(el, action) {
  el.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    pending.push(action);
    send();
  });
  el.addEventListener("contextmenu", (event) => event.preventDefault());
}

function bindHold(el) {
  let pointer = null;
  el.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    pointer = event.pointerId;
    el.setPointerCapture(pointer);
    useHeld = true;
    pending.push("use");
    send();
  });
  function end(event) {
    if (event.pointerId !== pointer) return;
    pointer = null;
    useHeld = false;
  }
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("contextmenu", (event) => event.preventDefault());
}

function connect(id) {
  const gen = ++socketGen;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/api/runs/${id}/play?player_id=${playerId}`);
  ws = socket;
  socket.onmessage = (event) => {
    if (gen !== socketGen) return;
    accept(JSON.parse(event.data));
  };
  socket.onclose = () => {
    if (gen !== socketGen || screen !== "play") return;
    setTimeout(() => {
      if (screen === "play" && gen === socketGen) connect(id);
    }, 700);
  };
}

function closeSocket() {
  socketGen += 1;
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
}

function accept(view) {
  const previous = snaps.length ? snaps[snaps.length - 1].view : null;
  snaps.push({ t: performance.now(), view });
  if (snaps.length > 2) snaps.shift();
  if (previous) noteSounds(previous, view);
  if (view.say_seq !== spokenSeq) {
    spokenSeq = view.say_seq;
    if (view.say_kind === "bark") speak(view.say);
  }
  paintHud(view);
  paintVeil(view);
}

function paintHud(view) {
  const floor = document.querySelector("#floor");
  const ammo = document.querySelector("#ammo");
  const pills = document.querySelector("#pills");
  const log = document.querySelector("#log");
  const map = document.querySelector("#map");
  const gun = document.querySelector("#gun");
  if (!floor) return;
  const clock = `${String(Math.floor(view.time / 60)).padStart(2, "0")}:${String(view.time % 60).padStart(2, "0")}`;
  floor.textContent = `${view.floor_name} · ${view.rank_name} · ${clock}`;
  const player = view.player;
  ammo.textContent = `${player.bullets} rounds · ${player.grenades} bombs · ${player.keys} keys`;
  const marks = [
    [player.holstered ? "Holstered" : "Pistol out", !player.holstered],
    ["Coat", player.uniform],
    ["Vest", player.vest],
    ["Plans", player.plans],
    ["Schnapps", player.drunk > 0],
  ];
  pills.innerHTML = marks.filter((item) => item[0] === "Holstered" || item[0] === "Pistol out" || item[1])
    .map(([label, on]) => `<span class="pill${on ? " on" : ""}">${label}</span>`).join("");
  log.innerHTML = (view.log || []).slice(-3).map((line) => `<div>${esc(line)}</div>`).join("");
  gun.textContent = player.holstered ? "Draw" : "Holster";
  const cols = Math.max(...view.map.map((cell) => cell.gx)) + 1;
  const rows = Math.max(...view.map.map((cell) => cell.gy)) + 1;
  map.style.gridTemplateColumns = `repeat(${cols}, 9px)`;
  const cells = [];
  for (let gy = 0; gy < rows; gy += 1) {
    for (let gx = 0; gx < cols; gx += 1) {
      const cell = view.map.find((item) => item.gx === gx && item.gy === gy);
      const classes = [cell && cell.seen ? "seen" : "", cell && cell.here ? "here" : "", cell && cell.mark === "exit" ? "exit" : ""];
      cells.push(`<i class="${classes.filter(Boolean).join(" ")}"></i>`);
    }
  }
  map.innerHTML = cells.join("");
}

function paintVeil(view) {
  const veil = document.querySelector("#veil");
  if (!veil || !view) return;
  if (view.status === "playing") {
    if (!veil.querySelector("#close-help")) {
      veil.classList.add("hidden");
      veil.dataset.key = "";
    }
    return;
  }
  const key = `${view.status}:${view.death || ""}`;
  if (veil.dataset.key === key) return;
  veil.dataset.key = key;
  veil.classList.remove("hidden");
  if (view.status === "dead") {
    const copy = view.death === "explosive"
      ? "The blast brings the wing down. Command will draw a new castle, and your rank stays."
      : "Shot. You wake in the cell. The rooms are the same and the sentries are back on their posts. Chests are shut again. Doors you broke stay open.";
    veil.innerHTML = `
      <div class="sheet">
        <h2>${view.death === "explosive" ? "Buried" : "Caught"}</h2>
        <p>${copy}</p>
        <button class="primary" type="button" id="again">Wake up</button>
      </div>`;
    veil.querySelector("#again").addEventListener("click", async () => {
      await api(`/api/runs/${runId}/continue?player_id=${playerId}`, { method: "POST" });
      if (ws && ws.readyState === 1) ws.send(JSON.stringify({ cmd: "reload" }));
    });
    return;
  }
  const copy = view.player.plans
    ? "You are out, and the war plans are with you."
    : "You are out. The plans are still inside, so this escape does not promote you.";
  veil.innerHTML = `
    <div class="sheet">
      <h2>Out</h2>
      <p>${copy}</p>
      <button class="primary" type="button" id="report">Report in</button>
    </div>`;
  veil.querySelector("#report").addEventListener("click", async () => {
    const result = await api(`/api/runs/${runId}/resolve?player_id=${playerId}`, { method: "POST" });
    const line = result.promoted
      ? `Allied command promotes you to ${esc(result.rank_name)}.`
      : result.plans
        ? "The plans are filed. Your rank is unchanged."
        : "They wanted the plans. Your rank is unchanged.";
    veil.innerHTML = `
      <div class="sheet">
        <h2>${esc(result.rank_name)}</h2>
        <p>${line}</p>
        <button class="primary" type="button" id="mess">Back</button>
      </div>`;
    veil.querySelector("#mess").addEventListener("click", () => {
      document.body.classList.remove("playing");
      boot();
    });
  });
}

function shownView() {
  if (!snaps.length) return null;
  if (snaps.length === 1) return snaps[0].view;
  const older = snaps[0];
  const newer = snaps[1];
  if (older.view.room_id !== newer.view.room_id) return newer.view;
  const span = Math.max(40, newer.t - older.t);
  const renderTime = performance.now() - span;
  const t = Math.min(1, Math.max(0, (renderTime - older.t) / span));
  return mix(older.view, newer.view, t);
}

function lerp(a, b, t) { return a + (b - a) * t; }

function lerpAngle(a, b, t) {
  let diff = ((b - a + Math.PI) % (Math.PI * 2)) - Math.PI;
  if (diff < -Math.PI) diff += Math.PI * 2;
  return a + diff * t;
}

function mix(a, b, t) {
  if (t >= 1) return b;
  const view = { ...b, player: { ...b.player } };
  view.player.x = lerp(a.player.x, b.player.x, t);
  view.player.y = lerp(a.player.y, b.player.y, t);
  view.player.aim = lerpAngle(a.player.aim, b.player.aim, t);
  const guards = new Map(a.guards.map((guard) => [guard.id, guard]));
  view.guards = b.guards.map((guard) => {
    const previous = guards.get(guard.id);
    if (!previous) return guard;
    return {
      ...guard,
      x: lerp(previous.x, guard.x, t),
      y: lerp(previous.y, guard.y, t),
      facing: lerpAngle(previous.facing, guard.facing, t),
    };
  });
  const shots = new Map(a.projectiles.map((shot) => [shot.id, shot]));
  view.projectiles = b.projectiles.map((shot) => {
    const previous = shots.get(shot.id);
    if (!previous) return shot;
    return { ...shot, x: lerp(previous.x, shot.x, t), y: lerp(previous.y, shot.y, t) };
  });
  return view;
}

function frame() {
  if (screen === "play") draw();
  requestAnimationFrame(frame);
}

function draw() {
  const canvas = document.querySelector("#room");
  const view = shownView();
  if (!canvas || !view) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  const room = view.room;
  const scale = Math.min(width / room.w, height / room.h);
  const ox = (width - room.w * scale) / 2;
  const oy = (height - room.h * scale) / 2;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#100e0c";
  ctx.fillRect(0, 0, width, height);
  for (let y = 0; y < room.h; y += 1) {
    for (let x = 0; x < room.w; x += 1) {
      const tile = room.tiles[y * room.w + x];
      const px = ox + x * scale;
      const py = oy + y * scale;
      if (tile === "#") drawWall(ctx, px, py, scale);
      else drawFloor(ctx, px, py, scale, x, y);
      if (tile === "D") drawDoor(ctx, px, py, scale, true);
      if (tile === "d") drawDoor(ctx, px, py, scale, false);
      if (tile === "u" || tile === "n") drawStair(ctx, px, py, scale, tile === "u");
      if (tile === "e") drawGate(ctx, px, py, scale);
    }
  }
  for (const chest of view.chests) drawChest(ctx, ox, oy, scale, chest, view.picking);
  for (const blast of view.blasts) {
    ctx.fillStyle = `rgba(222, 120, 48, ${Math.max(0, blast.life) * 1.6})`;
    ctx.beginPath();
    ctx.arc(ox + blast.x * scale, oy + blast.y * scale, blast.r * scale, 0, Math.PI * 2);
    ctx.fill();
  }
  for (const guard of view.guards) drawPerson(ctx, ox, oy, scale, guard, false);
  drawPerson(ctx, ox, oy, scale, view.player, true);
  for (const shot of view.projectiles) {
    ctx.fillStyle = shot.kind === "grenade" ? "#1b1b1b" : "#f2d48a";
    ctx.beginPath();
    const radius = shot.kind === "grenade" ? scale * 0.14 : scale * 0.07;
    ctx.arc(ox + shot.x * scale, oy + shot.y * scale, radius, 0, Math.PI * 2);
    ctx.fill();
  }
  if (view.player.stun > 0.05) {
    ctx.fillStyle = `rgba(243, 234, 219, ${Math.min(0.45, view.player.stun)})`;
    ctx.fillRect(ox, oy, room.w * scale, room.h * scale);
  }
}

function drawFloor(ctx, px, py, scale, x, y) {
  const n = (x * 3 + y * 7) % 3;
  ctx.fillStyle = n === 0 ? "#2a3226" : n === 1 ? "#243028" : "#31392c";
  ctx.fillRect(px, py, scale + 0.5, scale + 0.5);
}

function drawWall(ctx, px, py, scale) {
  ctx.fillStyle = "#2a241e";
  ctx.fillRect(px, py, scale + 0.5, scale + 0.5);
  ctx.fillStyle = "#6f6558";
  ctx.fillRect(px + scale * 0.08, py + scale * 0.1, scale * 0.84, scale * 0.8);
  ctx.fillStyle = "#8d8374";
  ctx.fillRect(px + scale * 0.08, py + scale * 0.1, scale * 0.84, scale * 0.16);
}

function drawDoor(ctx, px, py, scale, closed) {
  ctx.fillStyle = closed ? "#6a4630" : "#0c0a08";
  ctx.fillRect(px, py, scale + 0.5, scale + 0.5);
  ctx.fillStyle = "#8d8374";
  ctx.fillRect(px, py, scale * 0.14, scale + 0.5);
  ctx.fillRect(px + scale * 0.86, py, scale * 0.14, scale + 0.5);
  if (closed) {
    ctx.fillStyle = "#e0b15a";
    ctx.fillRect(px + scale * 0.62, py + scale * 0.46, scale * 0.1, scale * 0.1);
  }
}

function drawStair(ctx, px, py, scale, up) {
  ctx.strokeStyle = "#d9d0c2";
  ctx.lineWidth = Math.max(1, scale * 0.06);
  ctx.beginPath();
  for (let i = 0; i < 3; i += 1) {
    const y = py + scale * (0.3 + i * 0.18);
    ctx.moveTo(px + scale * 0.25, y);
    ctx.lineTo(px + scale * 0.75, y);
  }
  ctx.stroke();
  ctx.fillStyle = "#d9d0c2";
  ctx.font = `${Math.max(10, scale * 0.28)}px sans-serif`;
  ctx.textAlign = "center";
  ctx.fillText(up ? "UP" : "DN", px + scale / 2, py + scale * 0.28);
}

function drawGate(ctx, px, py, scale) {
  ctx.fillStyle = "#3a3018";
  ctx.fillRect(px + scale * 0.12, py + scale * 0.12, scale * 0.76, scale * 0.76);
  ctx.strokeStyle = "#e0b15a";
  ctx.lineWidth = Math.max(2, scale * 0.08);
  ctx.strokeRect(px + scale * 0.18, py + scale * 0.18, scale * 0.64, scale * 0.64);
  ctx.fillStyle = "#e0b15a";
  ctx.font = `${Math.max(10, scale * 0.26)}px sans-serif`;
  ctx.textAlign = "center";
  ctx.fillText("OUT", px + scale / 2, py + scale * 0.58);
}

function drawChest(ctx, ox, oy, scale, chest, picking) {
  const x = ox + chest.x * scale;
  const y = oy + chest.y * scale;
  ctx.fillStyle = chest.open ? "#5c4634" : "#8d5a32";
  roundRect(ctx, x - scale * 0.28, y - scale * 0.22, scale * 0.56, scale * 0.44, scale * 0.06);
  ctx.fill();
  if (!chest.open) {
    ctx.fillStyle = "#e0b15a";
    ctx.fillRect(x - scale * 0.05, y - scale * 0.05, scale * 0.1, scale * 0.1);
  }
  if (picking && picking.id === chest.id) {
    const fraction = Math.max(0, Math.min(1, picking.progress / picking.need));
    ctx.fillStyle = "#1b1713";
    ctx.fillRect(x - scale * 0.3, y - scale * 0.42, scale * 0.6, scale * 0.08);
    ctx.fillStyle = "#e0b15a";
    ctx.fillRect(x - scale * 0.3, y - scale * 0.42, scale * 0.6 * fraction, scale * 0.08);
  }
}

function drawPerson(ctx, ox, oy, scale, actor, player) {
  const x = ox + actor.x * scale;
  const y = oy + actor.y * scale;
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.beginPath();
  ctx.ellipse(x, y + scale * 0.22, scale * 0.24, scale * 0.1, 0, 0, Math.PI * 2);
  ctx.fill();
  if (!player && actor.state === "dead") {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(actor.facing);
    ctx.fillStyle = "#5c4634";
    roundRect(ctx, -scale * 0.34, -scale * 0.14, scale * 0.68, scale * 0.28, scale * 0.1);
    ctx.fill();
    ctx.restore();
    return;
  }
  const coat = player ? (actor.uniform ? "#3f5e86" : "#6f9a45") : "#a68455";
  ctx.fillStyle = coat;
  roundRect(ctx, x - scale * 0.32, y - scale * 0.34, scale * 0.64, scale * 0.7, scale * 0.14);
  ctx.fill();
  if (!player && actor.kind === "ss") {
    ctx.fillStyle = "#e6e0d4";
    ctx.fillRect(x - scale * 0.18, y - scale * 0.16, scale * 0.36, scale * 0.32);
  }
  ctx.fillStyle = player ? "#f0d2b0" : "#e0c2a2";
  ctx.beginPath();
  ctx.arc(x, y - scale * 0.48, scale * 0.2, 0, Math.PI * 2);
  ctx.fill();
  const armed = player ? !actor.holstered : actor.state !== "surrender";
  if (armed) {
    const aim = player ? actor.aim : actor.facing;
    ctx.strokeStyle = "#1a1612";
    ctx.lineWidth = Math.max(2, scale * 0.08);
    ctx.beginPath();
    ctx.moveTo(x, y - scale * 0.02);
    ctx.lineTo(x + Math.cos(aim) * scale * 0.72, y - scale * 0.02 + Math.sin(aim) * scale * 0.72);
    ctx.stroke();
  }
  if (!player && actor.state === "surrender") {
    ctx.strokeStyle = "#f3eadb";
    ctx.lineWidth = Math.max(2, scale * 0.05);
    ctx.beginPath();
    ctx.moveTo(x - scale * 0.12, y - scale * 0.05);
    ctx.lineTo(x - scale * 0.22, y - scale * 0.28);
    ctx.moveTo(x + scale * 0.12, y - scale * 0.05);
    ctx.lineTo(x + scale * 0.22, y - scale * 0.28);
    ctx.stroke();
  }
  if (!player && actor.state === "alert") {
    ctx.fillStyle = "#e0b15a";
    ctx.font = `${Math.max(12, scale * 0.34)}px sans-serif`;
    ctx.textAlign = "center";
    ctx.fillText("!", x, y - scale * 0.55);
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

boot();
