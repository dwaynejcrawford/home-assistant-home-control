# Changelog

## 1.0.13

- Show Play/Pause media controls only when the Home Assistant media player advertises play or pause capability.


## 1.0.12

- Add full media detail views from compact room media cards.
- Add capability-aware previous, next, source, shuffle, and repeat controls.
- Keep existing safe media service allowlists and artwork proxy behavior.

## 1.0.11

- Add a read-only Network page for WAN, Wi-Fi infrastructure, client, and other telemetry.
- Add a structured `/api/network-signals` endpoint for future diagnostics.
- Surface initial network diagnostic facts, confidence, and read-only recommendations.

## 1.0.10

- Add a safe server-side media artwork proxy for media player entity pictures.
- Show media artwork and playback metadata in compact room media summaries.
- Move room media controls behind an expandable control surface.

## 1.0.9

- Replace raw room audit blocks with cleaner household-facing room summaries.
- Clarify Main Bedroom room temperature versus the whole-home thermostat.

## 1.0.8

- Refine room lighting hierarchy with Main Bedroom primary lamp handling.
- Collapse individual room lights by default outside Main Bedroom.
- Add capability-driven warm/cool and color preset controls for supported lights.

## 1.0.7

- Move technical Home Assistant connectivity details below the primary home UI.
- Add a data-driven Home Status section for doors, cameras, climate, garage, security, and network telemetry availability.
- Start normalizing shared visual tokens for the mobile-first card system.

## 0.1.0

- Initial supervised Home Assistant connection
- Ingress interface
- Read-only Home Assistant state bootstrap
- Phone-first favorites shell
