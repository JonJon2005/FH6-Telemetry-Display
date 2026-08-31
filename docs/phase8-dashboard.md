# Phase 8: main driving dashboard

Phase 8 adds the primary live driving view at `/dashboard`. The root URL now redirects there, while `/debug` remains the parser and network diagnostic page.

## Open the dashboard

Start the service:

```powershell
python -m app.main
```

Then use either address printed at startup:

```text
This PC:          http://localhost:50415
Another device:  http://192.168.1.205:50415
```

Both redirect to `/dashboard`. Use the IP printed on your own machine if it differs.

To exercise the display without FH6:

```powershell
python tools\replay_capture.py captures\first-drive.fh6cap --speed 1
```

## Instruments

The main view contains:

- large speed and gear readouts;
- current/maximum RPM and a 24-segment rev bar with red shift-zone segments;
- horsepower, torque, and boost;
- throttle, brake, clutch, handbrake, and signed steering position;
- four tire temperatures around a plan-view car marker;
- current/last/best lap, lap number, race position, and race/free-roam state;
- estimated lateral and longitudinal G visualization;
- telemetry/WebSocket status, packet rate, sender, packet size, timestamp, and sequence.

The G meter divides the protocol's likely acceleration values by standard gravity. Because the source acceleration unit remains classified as `LIKELY`, the dashboard visibly labels this display **ESTIMATED** rather than presenting it as a confirmed measurement.

## Controls

- **MPH/KMH** switches speed units and remembers the selection locally in that browser.
- **°C/°F** switches tire-temperature units and remembers the selection.
- The sliders button opens dashboard customization. Colors, panel order, panel
  visibility, engine-output visibility, and digital/analog speedometer mode are
  saved locally in that browser.
- The optional realtime clock follows the viewing device's system time and locale.
- The corner-frame button enters or exits browser fullscreen where supported.
- **Debug** opens the Phase 5/10 engineering page.

No external fonts, scripts, images, CDNs, or frontend framework are required.

## Realtime behavior

The dashboard consumes the compact `/ws/telemetry` production stream at the configured display frequency, defaulting to 20 Hz. Speed and RPM are interpolated with `requestAnimationFrame`; bars and markers use short linear transitions. The browser does not receive every native UDP packet.

If the WebSocket closes, the page:

1. marks itself as reconnecting;
2. fetches `/api/telemetry` as a fallback;
3. retries with bounded exponential backoff;
4. preserves the last valid instrument readings;
5. shows a waiting overlay whenever current FH6 telemetry is stale.

The `prefers-reduced-motion` media query disables dashboard transitions for users who request it.

## Responsive layouts

The page uses a content-first CSS grid rather than scaling a desktop canvas:

- **Desktop:** three-column layout; primary instruments span two columns, with race state alongside.
- **Laptop/small tablet:** two-column layout with full-width primary instruments and connection panel.
- **Mobile portrait:** one-column instrument order, compact header, narrower gear/speed cluster, two-column connection details, and touch-sized controls.
- **Short landscape tablet/handheld:** compact three-column telemetry layout with reduced vertical spacing and retained header connection state; taller landscape tablets use the roomy two-column layout.
- **Very narrow phone:** optional header controls collapse while the essential unit switch and connection state remain.

All layouts permit normal document scrolling rather than clipping panels to a fixed viewport height. Safe-area insets are honored for the header and waiting notification.

## Visual direction

The dashboard deliberately avoids landing-page styling. It uses flat charcoal surfaces, hard two-pixel panel corners, restrained borders, condensed Windows instrumentation typography, a single redline accent, and state-driven color. It contains no eyebrow text, decorative gradients, glass blur, giant marketing copy, stock imagery, or ornamental pills.

## Verification

The automated suite contains 84 tests. Dashboard-specific checks cover routing,
assets, unique element IDs, safe button markup, JavaScript element references,
customization persistence, speedometer modes, the realtime clock, production-stream
usage, reconnect fallback, animation smoothing, reduced motion, responsive
breakpoints, and the prohibited visual patterns above.

An end-to-end 2× replay delivered all 410 capture packets to the service. The dashboard HTML, CSS, and JavaScript each returned HTTP 200; the production sequence reached 410 and exposed live speed, gear, RPM, inputs, tires, motion, and race data. JavaScript syntax validation also passed.
