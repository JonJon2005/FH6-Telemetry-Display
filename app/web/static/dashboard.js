"use strict";

const byId = id => document.getElementById(id);
const elements = Object.fromEntries([
  "connection-light","connection-label","header-rate","speed-value","speed-unit","gear-value",
  "rpm-value","rpm-limit","power-value","torque-value","boost-value","race-mode","race-position",
  "lap-number","current-lap","last-lap","best-lap","throttle-bar","throttle-value","brake-bar",
  "brake-value","clutch-bar","clutch-value","handbrake-bar","handbrake-value","steering-marker",
  "steering-value","g-dot","lateral-g","longitudinal-g","socket-state","source-value","packet-rate",
  "packet-size","last-packet","sequence-value","stale-overlay","unit-toggle","temp-toggle",
  "fullscreen-button"
].map(id => [id, byId(id)]));

const tires = {
  front_left: byId("tire-fl"), front_right: byId("tire-fr"),
  rear_left: byId("tire-rl"), rear_right: byId("tire-rr")
};
const state = {speedUnit:"mph",tempUnit:"c",targetSpeed:0,displaySpeed:0,targetRpm:0,displayRpm:0,lastFrame:performance.now(),socketOpen:false,lastPayload:null,retry:750};
try { state.speedUnit = localStorage.getItem("fh6-speed-unit") || "mph"; state.tempUnit = localStorage.getItem("fh6-temp-unit") || "c"; } catch {}

for (let index=0; index<24; index++) { const segment=document.createElement("i"); segment.setAttribute("aria-hidden","true"); byId("rev-lights").append(segment); }
const revSegments = [...byId("rev-lights").children];

const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
const number=(value,digits=0)=>Number.isFinite(value)?Number(value).toFixed(digits):"—";
const signed=(value)=>`${value>=0?"+":""}${number(value,2)}`;
function lapTime(seconds){if(!Number.isFinite(seconds)||seconds<=0)return "--:--.---";const minutes=Math.floor(seconds/60),rest=seconds-minutes*60;return `${String(minutes).padStart(2,"0")}:${rest.toFixed(3).padStart(6,"0")}`}
function setText(name,value){elements[name].textContent=value}
function setBar(name,value){elements[name].style.width=`${clamp(value||0,0,100)}%`}

function render(payload){state.lastPayload=payload;const connection=payload.connection||{},telemetry=payload.telemetry;
  const live=Boolean(connection.connected&&telemetry);elements["connection-light"].className=`status-light ${live?"live":connection.traffic_active?"stale":""}`;
  setText("connection-label",live?"Telemetry live":connection.traffic_active?"Unrecognized traffic":"Waiting for telemetry");
  setText("header-rate",`${number(connection.packets_per_second,0)} pkt/s`);setText("socket-state",state.socketOpen?"WEBSOCKET LIVE":"RECONNECTING");
  setText("source-value",connection.sender||"—");setText("packet-rate",`${number(connection.packets_per_second,1)} /s`);setText("packet-size",connection.latest_packet_size?`${connection.latest_packet_size} B`:"—");setText("last-packet",connection.last_received_at?new Date(connection.last_received_at).toLocaleTimeString():"—");setText("sequence-value",`SEQ ${payload.sequence||0}`);
  elements["stale-overlay"].classList.toggle("visible",!live);
  elements["stale-overlay"].style.display=live?"none":"flex";
  if(!telemetry)return;
  const vehicle=telemetry.vehicle,inputs=telemetry.inputs,race=telemetry.race,wheels=telemetry.wheels,motion=telemetry.motion;
  state.targetSpeed=state.speedUnit==="mph"?vehicle.speed.miles_per_hour:vehicle.speed.kilometers_per_hour;state.targetRpm=vehicle.current_engine_rpm||0;
  setText("speed-unit",state.speedUnit.toUpperCase());setText("unit-toggle",state.speedUnit.toUpperCase());
  const gear=String(inputs.gear.label).startsWith("unknown")?String(inputs.gear.raw):inputs.gear.label;setText("gear-value",gear);elements["gear-value"].title=inputs.gear.is_unverified_shift_state?"Unverified shift-state code":"";
  setText("rpm-limit",`/ ${number(vehicle.engine_max_rpm,0)}`);const rpmFraction=clamp(vehicle.engine_rpm_fraction||0,0,1.2);revSegments.forEach((segment,index)=>{const active=index/revSegments.length<rpmFraction;segment.classList.toggle("active",active);segment.classList.toggle("hot",active&&index>=19)});
  setText("power-value",number(vehicle.power.mechanical_horsepower,0));setText("torque-value",number(vehicle.torque.pound_feet,0));setText("boost-value",number(vehicle.boost.source_psi,1));
  setText("race-mode",race.is_race_on?"RACE ON":"FREE ROAM");elements["race-mode"].classList.toggle("active",race.is_race_on);setText("race-position",race.race_position>0?race.race_position:"—");setText("lap-number",race.lap_number>0?race.lap_number:"—");setText("current-lap",lapTime(race.current_lap_seconds));setText("last-lap",lapTime(race.last_lap_seconds));setText("best-lap",lapTime(race.best_lap_seconds));
  for(const [name,input] of [["throttle",inputs.throttle],["brake",inputs.brake],["clutch",inputs.clutch],["handbrake",inputs.handbrake]]){setBar(`${name}-bar`,input.percent);setText(`${name}-value`,number(input.percent,0))}
  const steer=clamp(inputs.steering.percent||0,-100,100);elements["steering-marker"].style.left=`${50+steer*.46}%`;setText("steering-value",`${steer>=0?"+":""}${number(steer,0)}%`);
  for(const [corner,wheel] of Object.entries(wheels)){const value=state.tempUnit==="c"?wheel.tire_temperature.celsius:wheel.tire_temperature.source_fahrenheit,root=tires[corner];root.querySelector("strong").textContent=number(value,0);root.querySelector("small").textContent=`°${state.tempUnit.toUpperCase()}`;const celsius=wheel.tire_temperature.celsius;root.classList.toggle("warm",celsius>=85&&celsius<110);root.classList.toggle("hot",celsius>=110)}
  const lateral=(motion.acceleration_source.x||0)/9.80665,longitudinal=(motion.acceleration_source.z||0)/9.80665;setText("lateral-g",signed(lateral));setText("longitudinal-g",signed(longitudinal));elements["g-dot"].style.left=`${50+clamp(lateral/2,-1,1)*42}%`;elements["g-dot"].style.top=`${50-clamp(longitudinal/2,-1,1)*42}%`;
}

function animate(now){const elapsed=Math.min(100,now-state.lastFrame);state.lastFrame=now;const blend=1-Math.pow(.001,elapsed/180);state.displaySpeed+=(state.targetSpeed-state.displaySpeed)*blend;state.displayRpm+=(state.targetRpm-state.displayRpm)*blend;setText("speed-value",number(Math.max(0,state.displaySpeed),0));setText("rpm-value",number(Math.max(0,state.displayRpm),0));requestAnimationFrame(animate)}

async function fetchLatest(){try{const response=await fetch("/api/telemetry",{cache:"no-store"});if(response.ok)render(await response.json())}catch{}}
function connect(){const scheme=location.protocol==="https:"?"wss":"ws",socket=new WebSocket(`${scheme}://${location.host}/ws/telemetry`);socket.onopen=()=>{state.socketOpen=true;state.retry=750;setText("socket-state","WEBSOCKET LIVE")};socket.onmessage=event=>render(JSON.parse(event.data));socket.onerror=()=>socket.close();socket.onclose=()=>{state.socketOpen=false;setText("socket-state","RECONNECTING");fetchLatest();setTimeout(connect,state.retry);state.retry=Math.min(8000,state.retry*1.6)}}

elements["unit-toggle"].addEventListener("click",()=>{state.speedUnit=state.speedUnit==="mph"?"kmh":"mph";try{localStorage.setItem("fh6-speed-unit",state.speedUnit)}catch{}if(state.lastPayload)render(state.lastPayload)});
elements["temp-toggle"].addEventListener("click",()=>{state.tempUnit=state.tempUnit==="c"?"f":"c";setText("temp-toggle",`°${state.tempUnit.toUpperCase()}`);try{localStorage.setItem("fh6-temp-unit",state.tempUnit)}catch{}if(state.lastPayload)render(state.lastPayload)});
elements["fullscreen-button"].addEventListener("click",async()=>{try{if(!document.fullscreenElement)await document.documentElement.requestFullscreen();else await document.exitFullscreen()}catch{}});
setText("unit-toggle",state.speedUnit.toUpperCase());setText("speed-unit",state.speedUnit.toUpperCase());setText("temp-toggle",`°${state.tempUnit.toUpperCase()}`);connect();requestAnimationFrame(animate);setInterval(()=>{if(!state.socketOpen)fetchLatest()},2000);
