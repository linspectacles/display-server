# Display Server 0.0.5 — QA

## Scope

- Five distinct inventories: Session, Display Stack, Outputs, Modes, Protocols.
- Current launch environment only. One automatic snapshot on first visible opening; Refresh List manually reacquires; no polling.
- No use of XWayland's emulated RandR results for physical output reporting.
- Output-management data chosen from one authoritative source at a time, with fallback to partial `wl_output` when available.
- Read-only command argv: `loginctl show-session`, `wayland-info`, `kscreen-doctor -j`, `wlr-randr --json`, `xrandr --query`, `xdpyinfo`, optional known running-system executable version flags; optional read-only Mutter `GetCurrentState`.
- Same-user process candidates are excluded unless independent session/socket evidence ties them to this session; no desktop-name-only compositor attribution.

## Verified in the build environment

- Python syntax compilation: passed.
- Headless collector unittest fixtures, 0.0.3 release contracts and new 0.0.4 audit regressions: 23 passed in 0.0.4; 25 passed in 0.0.5.
- XML/manifest and package structure sanity checks: passed.
- No `pkexec`, shell execution, output changes, capture loops, or privileged helpers.

## Not verified

- The build environment does **not** have PyQt6, so no Qt graphical smoke test was possible.
- No live Wayland/X11 session or GNOME/KDE/wlroots compositor was available for end-to-end testing.
- Target-host visual appearance has not been smoke-tested because PyQt6 and a desktop session are unavailable here. The accepted shared shell and icon remain byte-for-byte identical to Kernel Modules 0.0.5.

## Suggested target-host smoke test

1. Install PyQt6 and optional source utilities. Run `python3 standalone.py` from the applet directory.
2. Confirm titlebar, Options, all five views, selection/metadata synchronization and sorting.
3. In a Wayland session with `DISPLAY` set, confirm no XWayland `xrandr` probe occurs.
4. Verify GNOME `GetCurrentState` and KDE KScreen source behavior on actual desktops.
5. Confirm absence of output manipulation, runtime privilege, and hidden polling.

## 0.0.2 UI parity

- `_support.py`: byte-for-byte reference copy from Kernel Modules 0.0.5.
- `icon.png`: byte-for-byte reference copy from Kernel Modules 0.0.5.
- `collectors.py` and collector tests: byte-for-byte unchanged from Display Server 0.0.1.
- Confirm `BaseInspectorTab` inheritance and authoritative Options, table, metadata and status structures.

## 0.0.3 acceptance checks

- First visible `showEvent` queues exactly one acquisition, without collecting in the constructor or during module import.
- Hidden Hub applet construction must not trigger acquisition; subsequent hide/show does not reacquire unless Refresh List is selected.
- Refresh List and Shift+F5 continue to reacquire all five views.
- All user-facing naming is Display Server; package and applet ID have no inspector suffix.
- `collectors.py`, `_support.py`, `icon.png`, `LICENSE`, and standalone entrypoint are unchanged from 0.0.2.
- Real PyQt6 graphical verification is required on target desktop.

## 0.0.4 audit closure: all section 2 / 3 findings

| Original audit | Patch | Test/validation |
|---|---|---|
| 1. Initial Session column widths/visibility | Restore active view in constructor; register callback for all views | Static UI contract; Fedora GUI still required |
| 2. Numeric sorting | `inventory_sort_key` on PID/version/Hz/scale/resolution/position | Numeric fixtures |
| 3. Negative X11 geometry | Signed XRandR coordinates; rotation/physical size details | Negative-offset fixture |
| 4. Empty inventory explanation | Explicit `empty_reasons`; show notes in existing Metadata Details/status | Empty Wayland fixture; Qt GUI still required |
| 5. GUI-blocking collection | `QThread` collector, UI-only result slot, bounded shutdown | Static contract; Qt GUI still required |
| 6. Compositor identity | Session/socket-corroborated `/proc` candidates; Mutter API response explicit; no name-based claims | Cross-session and inode fixtures; live access still required |
| 7. XWayland | Reconcile matching process with Wayland-session `DISPLAY`; otherwise label unverified | Socket fixture and no-XRandR fixture |
| 8. Display-stack versions | Known running system executable `--version`/`-version` only | Version parser fixture; live binaries still required |
| 9. Physical/logical dimensions/orientation | XRandR, Mutter, KDE, wlroots source-backed metadata | X11/GNOME/KDE fixtures |
| 10. HDR/VRR/colour | KScreen capability bits, explicit enablement/policy, Mutter evidence | HDR off / supported fixture; live variants unverified |
| 11. Mutter disabled outputs | Logical-monitor membership → enabled/disabled | Connected-but-disabled GNOME fixture |
| 12. Missing XDG_SESSION_ID | `loginctl self`, type/user/seat-corroborated `auto` fallback | Session fallback fixtures |

These tests verify parser/logic/static contracts, not actual PyQt rendering or desktop D-Bus behavior. No claims of complete GNOME/KDE/wlroots runtime parity are made until host testing.

## 0.0.5 top-right View placement

- The existing **View:** label and selector are moved from the second (Search) row into the first (header/action) row, immediately before Refresh List / Options.
- The shared `_support.py` and official icon are unchanged; no duplicated dropdown or additional control is introduced.
- The existing signal/slot wiring, Ctrl+1–5 shortcuts, saved view choice, and per-view table state remain attached to the same QComboBox instance.
- A Qt-free widget-layout harness verifies the position/order; host PyQt6 GUI smoke test is still required.
