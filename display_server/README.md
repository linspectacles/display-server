# Display Server — LinSpectacles

**Version:** `0.0.5`  
**Applet ID:** `linspectacles-display-server`  
**Organisation ID:** `linspectacles`  
**Copyright:** 2026 `brunonlinespace`  
**Licence:** GPL-3.0-or-later

A standalone, read-only Linux graphical-session applet. Its five inventories are **Session**, **Display Stack**, **Outputs**, **Modes**, and **Protocols**. The five-view snapshot is acquired automatically on first display; Refresh List explicitly reacquires it. There is no polling or background monitoring. Acquisition runs in a bounded Qt worker, leaving the interface responsive.

## Launch

From the directory **containing** `linspectacles_display_server/`:

```bash
python3 -m linspectacles_display_server.standalone
```

Or inside the applet directory:

```bash
python3 standalone.py
```

Requires Python 3.10+ and PyQt6. The application runs without the Hub. The Hub can discover `applet.json` and call `create_applet(parent=None)`.

## Optional read-only source tools

- `loginctl show-session` (explicit session ID, then `self`, or validated `auto` fallback)
- `wayland-info` for Wayland registry and basic output advertisement
- `kscreen-doctor -j` for KDE/KScreen outputs
- `python3-gobject` (Gio) for GNOME Mutter's read-only `GetCurrentState` D-Bus method
- `wlr-randr --json` where the wlroots output-manager protocol is advertised
- `xrandr --query` / `xdpyinfo` for native X11 only
- Read-only `/proc`, `/proc/net/unix` and display-socket inode correlation for evidenced compositor/XWayland relationships; known system executable version flags where safe

The applet degrades gracefully if optional tools are unavailable. It does not elevate privileges or change display configuration. A `Wayland` session is not reclassified as X11 because it also has `DISPLAY` set. XWayland's RandR emulation is deliberately excluded from display-output collection.

**Interpretation limits:** Protocol advertisements are not feature-state guarantees. Ordinary Wayland clients may not have access to monitor management details. Compositor-specific sources are never merged with partial `wl_output` as though they were one coherent authoritative dataset. Same-user process names alone are never treated as active-session evidence: process records require session corroboration or display-socket ownership. Version probes are limited to verified running executables in recognised system directories; unsupported versions remain unreported. Output-to-GPU ownership is not inferred.

Branding: the official LinSpectacles `icon.png` is copied unchanged from the supplied authoritative Kernel Modules 0.0.5 source package.

The About dialog includes the **proposed** repository address `https://github.com/linspectacles/display-server`; this ZIP does **not** create or publish a repository.

## Verification

```bash
python3 -m unittest discover -s linspectacles_display_server/tests -v
python3 -m compileall -q linspectacles_display_server
```

Headless test fixtures cover collector parsing and the Wayland/X11 safety boundaries. GUI smoke testing requires an actual PyQt6 graphical session.

## 0.0.2 presentation correction

The application shell now derives from the **exact supplied Kernel Modules 0.0.5 shared `_support.py`** with the same compact header, Search/View filter row, inventory and Metadata Details splitter, read-only styled metadata, italic status area, right-click column visibility, and Options Appearance/Sources/Export/About treatments. F3, Shift+F5, Ctrl+L, Ctrl+/, and Ctrl+1–5 follow the family shortcut conventions. No display collector or data parser was modified from 0.0.1.

## 0.0.3 eager acquisition and name correction

- Visible name and metadata now use **Display Server**; technical ID remains `linspectacles-display-server` and package folder remains `linspectacles_display_server`.
- On the first visible opening, the applet acquires one snapshot for all five views. Importing or constructing a hidden applet does not trigger collection. View changes reuse the same snapshot.
- **Refresh List** and **Shift+F5** manually reacquire all five views; no background polling is introduced.
- Accepted Kernel Modules 0.0.5 UI shell and the 0.0.2 collectors are unchanged.
- Display-specific QSettings application group is renamed to **Display Server** (previous display preferences are not automatically migrated).

## 0.0.4 — audit remediation (sections 2 and 3)

- Restore per-view column widths/visibility even when opening directly into the saved or default Session view; keep the shared Kernel Modules shell and icon unchanged.
- Numeric sorting for PIDs, protocol versions, refresh, scale, resolution and signed positions.
- Parse negative X11 output positions; report orientation, physical output size and native geometry when exposed.
- Display inventory-empty acquisition explanations and available diagnostics in Metadata Details and status, distinct from an empty search.
- Run each intentional full snapshot on a bounded Qt worker; suppress concurrent refresh and complete outstanding workers before application shutdown. No continuous polling.
- Scope display-related process attribution to verified active display-socket ownership or corroborated login-session evidence, excluding known other-session processes. Do not infer compositor identity from desktop environment variables alone.
- Distinguish a Wayland session's `DISPLAY` endpoint from an XWayland process; associate XWayland only when session/endpoint evidence is present.
- Record display-stack versions only when a known running system executable can safely report one; never substitute an unrelated program of the same name.
- Include source-backed logical/physical output dimensions, rotation, reported HDR/WCG support and enabled state, VRR capability/policy and colour metadata where supported. Unknowns remain `Not exposed`.
- Report Mutter connected-versus-enabled state from current logical-monitor membership.
- With no `XDG_SESSION_ID`, try the calling logind session and only then a user/type/seat-corroborated `auto` fallback; `loginctl` remains optional.

All acquired values remain evidence-labelled. Platform-specific capabilities are not manufactured when APIs do not expose them. The original 0.0.3 eager-on-first-visible-open behaviour and standalone/Hub identity are unchanged. Run `python3 -m unittest discover -s linspectacles_display_server/tests -v`. Live graphical validation is still necessary on Fedora/Wayland/X11 and GNOME/KDE/wlroots.

## 0.0.5 — View control placement

- Move the existing **View:** label and five-view dropdown from the Search/filter row to the top-right header, immediately before **Refresh List** and **Options...**.
- Retain the inherited widgets and their signals, view selection/persistence, search, eager-on-first-opening acquisition, metadata, exports and the authoritative styling without alteration.
- No collectors, shared UI support, icon, or source-acquisition behaviour changed.
