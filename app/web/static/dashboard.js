"use strict";

const byId = id => document.getElementById(id);
const elements = Object.fromEntries([
  "connection-light", "connection-label", "header-rate", "local-clock", "speed-value", "speed-unit",
  "analog-speed-value", "analog-speed-unit", "analog-ticks", "speed-needle", "gear-value", "rpm-value",
  "rpm-limit", "power-value", "torque-value", "boost-value", "race-mode", "race-position", "lap-number",
  "current-lap", "last-lap", "best-lap", "throttle-bar", "throttle-value", "brake-bar", "brake-value",
  "clutch-bar", "clutch-value", "handbrake-bar", "handbrake-value", "steering-marker", "steering-value",
  "g-dot", "lateral-g", "longitudinal-g", "socket-state", "source-value", "packet-rate", "packet-size",
  "last-packet", "sequence-value", "stale-overlay", "unit-toggle", "temp-toggle", "fullscreen-button",
  "customize-button", "customizer", "customizer-close", "customizer-scrim", "dashboard-grid",
  "speedometer-mode", "clock-toggle", "power-toggle", "accent-color", "background-color", "panel-color",
  "text-color", "panel-settings", "reset-customization", "settings-saved", "power-strip"
].map(id => [id, byId(id)]));

const tires = {
  front_left: byId("tire-fl"),
  front_right: byId("tire-fr"),
  rear_left: byId("tire-rl"),
  rear_right: byId("tire-rr")
};

const panels = Object.fromEntries(
  [...document.querySelectorAll("[data-panel-id]")].map(panel => [panel.dataset.panelId, panel])
);
const panelDefinitions = [
  {id: "instruments", label: "Speedometer", hideable: false},
  {id: "race", label: "Race"},
  {id: "inputs", label: "Driver inputs"},
  {id: "tires", label: "Tire temperature"},
  {id: "motion", label: "G meter"},
  {id: "connection", label: "Connection"}
];
const panelDefinitionById = Object.fromEntries(panelDefinitions.map(item => [item.id, item]));
const panelIds = panelDefinitions.map(item => item.id);
const storageKey = "fh6-dashboard-preferences-v1";
const clockFormatter = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit", minute: "2-digit", second: "2-digit"
});
const defaultPreferences = {
  colors: {accent: "#ff3b30", background: "#090a0c", panel: "#111317", text: "#f4f5f6"},
  panelOrder: [...panelIds],
  hiddenPanels: [],
  showPower: true,
  speedometerMode: "digital",
  showClock: false
};

const state = {
  speedUnit: "mph",
  tempUnit: "c",
  targetSpeed: 0,
  displaySpeed: 0,
  targetRpm: 0,
  displayRpm: 0,
  lastFrame: performance.now(),
  socketOpen: false,
  lastPayload: null,
  retry: 750,
  analogScaleUnit: "",
  preferences: loadPreferences()
};

try {
  const savedSpeedUnit = localStorage.getItem("fh6-speed-unit");
  const savedTempUnit = localStorage.getItem("fh6-temp-unit");
  state.speedUnit = savedSpeedUnit === "kmh" ? "kmh" : "mph";
  state.tempUnit = savedTempUnit === "f" ? "f" : "c";
} catch {}

for (let index = 0; index < 24; index++) {
  const segment = document.createElement("i");
  segment.setAttribute("aria-hidden", "true");
  byId("rev-lights").append(segment);
}
const revSegments = [...byId("rev-lights").children];

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const number = (value, digits = 0) => Number.isFinite(value) ? Number(value).toFixed(digits) : "—";
const signed = value => `${value >= 0 ? "+" : ""}${number(value, 2)}`;

function lapTime(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "--:--.---";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(3).padStart(6, "0")}`;
}

function setText(name, value) {
  elements[name].textContent = value;
}

function setBar(name, value) {
  elements[name].style.width = `${clamp(value || 0, 0, 100)}%`;
}

function validHex(value, fallback) {
  return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : fallback;
}

function mixHex(first, second, amount) {
  const channels = hex => [1, 3, 5].map(index => Number.parseInt(hex.slice(index, index + 2), 16));
  const a = channels(first);
  const b = channels(second);
  return `#${a.map((channel, index) => Math.round(channel + (b[index] - channel) * amount).toString(16).padStart(2, "0")).join("")}`;
}

function freshDefaults() {
  return {
    colors: {...defaultPreferences.colors},
    panelOrder: [...defaultPreferences.panelOrder],
    hiddenPanels: [],
    showPower: true,
    speedometerMode: "digital",
    showClock: false
  };
}

function sanitizePreferences(raw) {
  const preferences = freshDefaults();
  if (!raw || typeof raw !== "object") return preferences;
  const rawColors = raw.colors && typeof raw.colors === "object" ? raw.colors : {};
  preferences.colors = {
    accent: validHex(rawColors.accent, defaultPreferences.colors.accent),
    background: validHex(rawColors.background, defaultPreferences.colors.background),
    panel: validHex(rawColors.panel, defaultPreferences.colors.panel),
    text: validHex(rawColors.text, defaultPreferences.colors.text)
  };
  const requestedOrder = Array.isArray(raw.panelOrder) ? raw.panelOrder.filter(id => panelIds.includes(id)) : [];
  preferences.panelOrder = [...new Set([...requestedOrder, ...panelIds])];
  preferences.hiddenPanels = Array.isArray(raw.hiddenPanels)
    ? [...new Set(raw.hiddenPanels.filter(id => id !== "instruments" && panelIds.includes(id)))]
    : [];
  preferences.showPower = raw.showPower !== false;
  preferences.speedometerMode = raw.speedometerMode === "analog" ? "analog" : "digital";
  preferences.showClock = raw.showClock === true;
  return preferences;
}

function loadPreferences() {
  try {
    return sanitizePreferences(JSON.parse(localStorage.getItem(storageKey) || "null"));
  } catch {
    return freshDefaults();
  }
}

let savedMessageTimer = 0;
function savePreferences() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(state.preferences));
    setText("settings-saved", "Saved on this device");
    clearTimeout(savedMessageTimer);
    savedMessageTimer = window.setTimeout(() => setText("settings-saved", "Auto-saved"), 1500);
  } catch {
    setText("settings-saved", "Could not save in this browser");
  }
}

function applyColors() {
  const {accent, background, panel, text} = state.preferences.colors;
  const root = document.documentElement.style;
  root.setProperty("--accent", accent);
  root.setProperty("--bg", background);
  root.setProperty("--header-bg", mixHex(background, panel, .35));
  root.setProperty("--surface", panel);
  root.setProperty("--surface-raised", mixHex(panel, text, .045));
  root.setProperty("--line", mixHex(panel, text, .12));
  root.setProperty("--line-strong", mixHex(panel, text, .2));
  root.setProperty("--text", text);
  document.querySelector('meta[name="theme-color"]').content = background;
}

function applyPreferences({persist = false, rebuildControls = true} = {}) {
  applyColors();
  const hidden = new Set(state.preferences.hiddenPanels);
  for (const id of state.preferences.panelOrder) {
    const panel = panels[id];
    panel.hidden = hidden.has(id);
    panel.style.order = String(state.preferences.panelOrder.indexOf(id));
    elements["dashboard-grid"].append(panel);
  }
  elements["dashboard-grid"].classList.add("custom-layout");
  panels.instruments.classList.toggle("speed-mode-analog", state.preferences.speedometerMode === "analog");
  elements["power-strip"].hidden = !state.preferences.showPower;
  elements["local-clock"].hidden = !state.preferences.showClock;
  elements["speedometer-mode"].value = state.preferences.speedometerMode;
  elements["clock-toggle"].checked = state.preferences.showClock;
  elements["power-toggle"].checked = state.preferences.showPower;
  elements["accent-color"].value = state.preferences.colors.accent;
  elements["background-color"].value = state.preferences.colors.background;
  elements["panel-color"].value = state.preferences.colors.panel;
  elements["text-color"].value = state.preferences.colors.text;
  updateClock();
  updateAnalogScale();
  if (rebuildControls) renderPanelControls();
  if (persist) savePreferences();
}

let draggedPanelId = null;
function renderPanelControls() {
  elements["panel-settings"].replaceChildren();
  state.preferences.panelOrder.forEach((id, index) => {
    const definition = panelDefinitionById[id];
    const row = document.createElement("li");
    row.className = "panel-setting";
    row.dataset.panelId = id;
    row.draggable = true;

    const grip = document.createElement("span");
    grip.className = "drag-grip";
    grip.textContent = "⋮⋮";
    grip.setAttribute("aria-hidden", "true");

    const visibility = document.createElement("label");
    visibility.className = "panel-visibility";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = !state.preferences.hiddenPanels.includes(id);
    checkbox.disabled = definition.hideable === false;
    checkbox.setAttribute("aria-label", `Show ${definition.label} panel`);
    checkbox.addEventListener("change", () => {
      const hidden = new Set(state.preferences.hiddenPanels);
      if (checkbox.checked) hidden.delete(id); else hidden.add(id);
      state.preferences.hiddenPanels = [...hidden];
      applyPreferences({persist: true});
    });
    const label = document.createElement("span");
    label.textContent = definition.label;
    visibility.append(checkbox, label);

    const actions = document.createElement("div");
    actions.className = "panel-move-actions";
    const up = document.createElement("button");
    up.type = "button";
    up.textContent = "↑";
    up.title = `Move ${definition.label} up`;
    up.setAttribute("aria-label", up.title);
    up.disabled = index === 0;
    up.addEventListener("click", () => movePanel(id, -1));
    const down = document.createElement("button");
    down.type = "button";
    down.textContent = "↓";
    down.title = `Move ${definition.label} down`;
    down.setAttribute("aria-label", down.title);
    down.disabled = index === state.preferences.panelOrder.length - 1;
    down.addEventListener("click", () => movePanel(id, 1));
    actions.append(up, down);

    row.addEventListener("dragstart", event => {
      draggedPanelId = id;
      row.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", id);
    });
    row.addEventListener("dragover", event => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      if (draggedPanelId !== id) row.classList.add("drag-target");
    });
    row.addEventListener("dragleave", () => row.classList.remove("drag-target"));
    row.addEventListener("drop", event => {
      event.preventDefault();
      if (draggedPanelId && draggedPanelId !== id) placePanelBefore(draggedPanelId, id);
    });
    row.addEventListener("dragend", () => {
      draggedPanelId = null;
      document.querySelectorAll(".panel-setting").forEach(item => item.classList.remove("dragging", "drag-target"));
    });
    row.append(grip, visibility, actions);
    elements["panel-settings"].append(row);
  });
}

function movePanel(id, direction) {
  const order = [...state.preferences.panelOrder];
  const from = order.indexOf(id);
  const to = clamp(from + direction, 0, order.length - 1);
  if (from === to) return;
  [order[from], order[to]] = [order[to], order[from]];
  state.preferences.panelOrder = order;
  applyPreferences({persist: true});
}

function placePanelBefore(sourceId, targetId) {
  const order = state.preferences.panelOrder.filter(id => id !== sourceId);
  order.splice(order.indexOf(targetId), 0, sourceId);
  state.preferences.panelOrder = order;
  draggedPanelId = null;
  applyPreferences({persist: true});
}

function updateClock() {
  const now = new Date();
  elements["local-clock"].dateTime = now.toISOString();
  elements["local-clock"].textContent = clockFormatter.format(now);
  elements["local-clock"].title = now.toLocaleDateString();
}

function updateAnalogScale() {
  if (state.analogScaleUnit === state.speedUnit) return;
  state.analogScaleUnit = state.speedUnit;
  elements["analog-ticks"].replaceChildren();
  const isMph = state.speedUnit === "mph";
  const maximum = isMph ? 200 : 320;
  const divisions = isMph ? 40 : 32;
  for (let index = 0; index <= divisions; index++) {
    const angle = -135 + (index / divisions) * 270;
    const mark = document.createElement("span");
    const major = index % 4 === 0;
    mark.className = `analog-mark${major ? " major" : ""}`;
    mark.style.transform = `rotate(${angle}deg)`;
    const tick = document.createElement("i");
    mark.append(tick);
    if (major) {
      const label = document.createElement("b");
      label.textContent = number((index / divisions) * maximum, 0);
      label.style.transform = `translateX(-50%) rotate(${-angle}deg)`;
      mark.append(label);
    }
    elements["analog-ticks"].append(mark);
  }
  setText("analog-speed-unit", state.speedUnit.toUpperCase());
}

function render(payload) {
  state.lastPayload = payload;
  const connection = payload.connection || {};
  const telemetry = payload.telemetry;
  const live = Boolean(connection.connected && telemetry);
  elements["connection-light"].className = `status-light ${live ? "live" : connection.traffic_active ? "stale" : ""}`;
  setText("connection-label", live ? "Telemetry live" : connection.traffic_active ? "Unrecognized traffic" : "Waiting for telemetry");
  setText("header-rate", `${number(connection.packets_per_second, 0)} pkt/s`);
  setText("socket-state", state.socketOpen ? "WEBSOCKET LIVE" : "RECONNECTING");
  setText("source-value", connection.sender || "—");
  setText("packet-rate", `${number(connection.packets_per_second, 1)} /s`);
  setText("packet-size", connection.latest_packet_size ? `${connection.latest_packet_size} B` : "—");
  setText("last-packet", connection.last_received_at ? new Date(connection.last_received_at).toLocaleTimeString() : "—");
  setText("sequence-value", `SEQ ${payload.sequence || 0}`);
  elements["stale-overlay"].classList.toggle("visible", !live);
  elements["stale-overlay"].style.display = live ? "none" : "flex";
  if (!telemetry) return;

  const {vehicle, inputs, race, wheels, motion} = telemetry;
  state.targetSpeed = state.speedUnit === "mph" ? vehicle.speed.miles_per_hour : vehicle.speed.kilometers_per_hour;
  state.targetRpm = vehicle.current_engine_rpm || 0;
  setText("speed-unit", state.speedUnit.toUpperCase());
  setText("analog-speed-unit", state.speedUnit.toUpperCase());
  setText("unit-toggle", state.speedUnit.toUpperCase());
  const gear = String(inputs.gear.label).startsWith("unknown") ? String(inputs.gear.raw) : inputs.gear.label;
  setText("gear-value", gear);
  elements["gear-value"].title = inputs.gear.is_unverified_shift_state ? "Unverified shift-state code" : "";
  setText("rpm-limit", `/ ${number(vehicle.engine_max_rpm, 0)}`);
  const rpmFraction = clamp(vehicle.engine_rpm_fraction || 0, 0, 1.2);
  revSegments.forEach((segment, index) => {
    const active = index / revSegments.length < rpmFraction;
    segment.classList.toggle("active", active);
    segment.classList.toggle("hot", active && index >= 19);
  });
  setText("power-value", number(vehicle.power.mechanical_horsepower, 0));
  setText("torque-value", number(vehicle.torque.pound_feet, 0));
  setText("boost-value", number(vehicle.boost.source_psi, 1));
  setText("race-mode", race.is_race_on ? "RACE ON" : "FREE ROAM");
  elements["race-mode"].classList.toggle("active", race.is_race_on);
  setText("race-position", race.race_position > 0 ? race.race_position : "—");
  setText("lap-number", race.lap_number > 0 ? race.lap_number : "—");
  setText("current-lap", lapTime(race.current_lap_seconds));
  setText("last-lap", lapTime(race.last_lap_seconds));
  setText("best-lap", lapTime(race.best_lap_seconds));
  for (const [name, input] of [["throttle", inputs.throttle], ["brake", inputs.brake], ["clutch", inputs.clutch], ["handbrake", inputs.handbrake]]) {
    setBar(`${name}-bar`, input.percent);
    setText(`${name}-value`, number(input.percent, 0));
  }
  const steer = clamp(inputs.steering.percent || 0, -100, 100);
  elements["steering-marker"].style.left = `${50 + steer * .46}%`;
  setText("steering-value", `${steer >= 0 ? "+" : ""}${number(steer, 0)}%`);
  for (const [corner, wheel] of Object.entries(wheels)) {
    const value = state.tempUnit === "c" ? wheel.tire_temperature.celsius : wheel.tire_temperature.source_fahrenheit;
    const root = tires[corner];
    root.querySelector("strong").textContent = number(value, 0);
    root.querySelector("small").textContent = `°${state.tempUnit.toUpperCase()}`;
    const celsius = wheel.tire_temperature.celsius;
    root.classList.toggle("warm", celsius >= 85 && celsius < 110);
    root.classList.toggle("hot", celsius >= 110);
  }
  const lateral = (motion.acceleration_source.x || 0) / 9.80665;
  const longitudinal = (motion.acceleration_source.z || 0) / 9.80665;
  setText("lateral-g", signed(lateral));
  setText("longitudinal-g", signed(longitudinal));
  elements["g-dot"].style.left = `${50 + clamp(lateral / 2, -1, 1) * 42}%`;
  elements["g-dot"].style.top = `${50 - clamp(longitudinal / 2, -1, 1) * 42}%`;
}

function animate(now) {
  const elapsed = Math.min(100, now - state.lastFrame);
  state.lastFrame = now;
  const blend = 1 - Math.pow(.001, elapsed / 180);
  state.displaySpeed += (state.targetSpeed - state.displaySpeed) * blend;
  state.displayRpm += (state.targetRpm - state.displayRpm) * blend;
  const speed = Math.max(0, state.displaySpeed);
  setText("speed-value", number(speed, 0));
  setText("analog-speed-value", number(speed, 0));
  setText("rpm-value", number(Math.max(0, state.displayRpm), 0));
  const maximum = state.speedUnit === "mph" ? 200 : 320;
  const needleAngle = -135 + clamp(speed / maximum, 0, 1) * 270;
  elements["speed-needle"].style.transform = `rotate(${needleAngle}deg)`;
  requestAnimationFrame(animate);
}

async function fetchLatest() {
  try {
    const response = await fetch("/api/telemetry", {cache: "no-store"});
    if (response.ok) render(await response.json());
  } catch {}
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws/telemetry`);
  socket.onopen = () => {
    state.socketOpen = true;
    state.retry = 750;
    setText("socket-state", "WEBSOCKET LIVE");
  };
  socket.onmessage = event => render(JSON.parse(event.data));
  socket.onerror = () => socket.close();
  socket.onclose = () => {
    state.socketOpen = false;
    setText("socket-state", "RECONNECTING");
    fetchLatest();
    setTimeout(connect, state.retry);
    state.retry = Math.min(8000, state.retry * 1.6);
  };
}

function openCustomizer() {
  document.body.classList.add("customizer-open");
  elements["customizer"].inert = false;
  elements["customizer"].setAttribute("aria-hidden", "false");
  elements["customize-button"].setAttribute("aria-expanded", "true");
  elements["customizer-close"].focus();
}

function closeCustomizer() {
  document.body.classList.remove("customizer-open");
  elements["customizer"].inert = true;
  elements["customizer"].setAttribute("aria-hidden", "true");
  elements["customize-button"].setAttribute("aria-expanded", "false");
  elements["customize-button"].focus();
}

elements["unit-toggle"].addEventListener("click", () => {
  state.speedUnit = state.speedUnit === "mph" ? "kmh" : "mph";
  state.analogScaleUnit = "";
  updateAnalogScale();
  try { localStorage.setItem("fh6-speed-unit", state.speedUnit); } catch {}
  setText("unit-toggle", state.speedUnit.toUpperCase());
  setText("speed-unit", state.speedUnit.toUpperCase());
  if (state.lastPayload) render(state.lastPayload);
});
elements["temp-toggle"].addEventListener("click", () => {
  state.tempUnit = state.tempUnit === "c" ? "f" : "c";
  setText("temp-toggle", `°${state.tempUnit.toUpperCase()}`);
  try { localStorage.setItem("fh6-temp-unit", state.tempUnit); } catch {}
  if (state.lastPayload) render(state.lastPayload);
});
elements["fullscreen-button"].addEventListener("click", async () => {
  try {
    if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
    else await document.exitFullscreen();
  } catch {}
});
elements["customize-button"].addEventListener("click", openCustomizer);
elements["customizer-close"].addEventListener("click", closeCustomizer);
elements["customizer-scrim"].addEventListener("click", closeCustomizer);
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.body.classList.contains("customizer-open")) closeCustomizer();
});
elements["speedometer-mode"].addEventListener("change", event => {
  state.preferences.speedometerMode = event.target.value === "analog" ? "analog" : "digital";
  applyPreferences({persist: true, rebuildControls: false});
});
elements["clock-toggle"].addEventListener("change", event => {
  state.preferences.showClock = event.target.checked;
  applyPreferences({persist: true, rebuildControls: false});
});
elements["power-toggle"].addEventListener("change", event => {
  state.preferences.showPower = event.target.checked;
  applyPreferences({persist: true, rebuildControls: false});
});
for (const [elementName, colorName] of [["accent-color", "accent"], ["background-color", "background"], ["panel-color", "panel"], ["text-color", "text"]]) {
  elements[elementName].addEventListener("input", event => {
    state.preferences.colors[colorName] = validHex(event.target.value, defaultPreferences.colors[colorName]);
    applyPreferences({persist: true, rebuildControls: false});
  });
}
elements["reset-customization"].addEventListener("click", () => {
  state.preferences = freshDefaults();
  state.analogScaleUnit = "";
  applyPreferences({persist: true});
});

setText("unit-toggle", state.speedUnit.toUpperCase());
setText("speed-unit", state.speedUnit.toUpperCase());
setText("temp-toggle", `°${state.tempUnit.toUpperCase()}`);
applyPreferences();
connect();
requestAnimationFrame(animate);
setInterval(updateClock, 1000);
setInterval(() => { if (!state.socketOpen) fetchLatest(); }, 2000);
