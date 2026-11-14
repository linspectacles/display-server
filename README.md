# Display Server Inspector

**Expose. Explore. Explain.**

Display Server Inspector is a read-only, on-demand Linux graphical-session inspector for Wayland/X11 session identity, display-stack evidence, reported outputs, modes and protocols.

Current release: **0.0.6**

Repository: <https://github.com/linspectacles/display-server>


<p align="center">
  <a href="https://github.com/brunonlinespace/brunonlinespace/blob/main/linspectacles/display-server.png">
    <img
      src="https://raw.githubusercontent.com/brunonlinespace/brunonlinespace/main/linspectacles/display-server.png"
      alt="Display Server Inspector screenshot"
      width="900"
    >
  </a>
</p>
## What Display Server Inspector is

Display Server Inspector answers a focused question: **what does the current graphical session report about its display stack, outputs, modes and exposed protocols?**

The applet keeps session identity separate from compositor/output-management evidence. A Wayland session is not reclassified as X11 merely because XWayland is present, and XWayland RandR data is deliberately not used as evidence for real physical outputs.

Collection is explicit and on demand. There is no background polling or continuous monitoring.

## Highlights

- Five inventories: **Session**, **Display Stack**, **Outputs**, **Modes** and **Protocols**.
- Preserves Wayland versus native X11 session identity.
- Optional `loginctl show-session` enrichment for the current graphical session.
- Wayland registry and basic `wl_output` information through `wayland-info` where available.
- KDE/KScreen output information through `kscreen-doctor -j` where available.
- GNOME/Mutter current monitor state through the read-only `org.gnome.Mutter.DisplayConfig.GetCurrentState` method where accessible.
- wlroots output-management information through `wlr-randr --json` where supported.
- Native X11 output/mode information through `xrandr --query`.
- Native X11 extension inventory through `xdpyinfo`.
- Explicit acquisition-source and interpretation notes in Metadata Details.
- No automatic output-to-GPU ownership inference.

## Data sources and acquisition

### Graphical session identity

- `XDG_SESSION_TYPE`
- `XDG_SESSION_ID`
- `XDG_CURRENT_DESKTOP`
- `WAYLAND_DISPLAY`
- `DISPLAY`
- `XDG_RUNTIME_DIR`
- optional `loginctl show-session`

### Display stack and endpoint evidence

- current session environment.
- relevant `/proc` process candidates, reported as candidates unless session association is actually established.

### Wayland

- `wayland-info`
- optional GNOME/Mutter `org.gnome.Mutter.DisplayConfig.GetCurrentState` through `python3-gobject`
- optional `kscreen-doctor -j`
- optional `wlr-randr --json`

### Native X11

- `xrandr --query`
- `xdpyinfo`

Optional sources degrade independently. Compositor-specific output sources are not merged with partial `wl_output` evidence as though they form one coherent authority.

## Interface

Display Server Inspector provides five selectable views:

- **Session** — session type, desktop, seat and state.
- **Display Stack** — reported compositor/X server/endpoints and relevant process evidence.
- **Outputs** — reported display outputs and currently exposed geometry/state.
- **Modes** — reported resolutions, refresh rates and current/preferred state.
- **Protocols** — reported Wayland interfaces or native X11 extensions.

Each view uses the standard LinSpectacles inventory + **Metadata Details** pattern. Search operates on the currently acquired records.

The **Options...** surface provides Appearance, Sources, Export and About. Export operates on the current display-server view and can include acquisition source and Metadata Details.

## Read-only and scope boundaries

Display Server Inspector does not change display configuration, enable or disable outputs, switch modes, move displays or modify compositor settings.

Important interpretation boundaries:

- Wayland with XWayland remains a **Wayland** session.
- XWayland RandR does not establish real physical output properties.
- An advertised Wayland protocol does not prove that a feature is enabled or currently usable.
- Unreported information is not automatically equivalent to unsupported information.
- Ordinary Wayland clients may not be permitted to see full monitor-management state.
- `/proc` process candidates are not asserted to belong to the active session without evidence.
- Output-to-GPU ownership is **not inferred**.

That last relationship belongs naturally with future Hub correlation between Display Server Inspector and GPU Inspector rather than being fabricated locally.

## Useful keyboard shortcuts

| Command | Shortcut |
| --- | --- |
| Toggle Metadata Details | `F3` |
| Refresh display inventory | `Shift+F5` |
| Toggle Metadata Details layout | `Ctrl+L` |
| Options | `Ctrl+/` |
| Session | `Ctrl+1` |
| Display Stack | `Ctrl+2` |
| Outputs | `Ctrl+3` |
| Modes | `Ctrl+4` |
| Protocols | `Ctrl+5` |

## Running from source

The supplied source is directly runnable on Linux. The Python-side requirements are:

- Python 3.10 or later.
- PyQt6 for the graphical interface.

Create a local virtual environment if you do not already have the required Python packages in the environment you want to use:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install PyQt6
python3 -m linspectacles_display_server.standalone
```

The command-line and compositor-specific tools listed under **Data sources and acquisition** are optional. Their absence limits only the evidence they would have supplied.

No RPM installation instructions are included in this README.

## LinSpectacles Hub

This applet can run independently, but it can also be installed and used inside **[LinSpectacles Hub](https://github.com/linspectacles/linspectacles-hub)**.

LinSpectacles Hub is the optional workbench for the LinSpectacles applet family. It provides shared applet discovery, navigation and management while each inspector remains independently runnable.

To install a portable or user applet through the Hub, open **Configuration... → Applets** and add the applet ZIP. Once discovered, the applet can be enabled and opened from the Hub navigation.

System-installed applets are discovered by the Hub from its system applet store and remain managed by the system package manager.

## Source layout and LinSpectacles integration

The applet source is contained in:

```text
linspectacles_display_server/
├── __init__.py
├── standalone.py
├── LICENSE
├── applet.json
├── README.md
└── display_server/
    ├── __init__.py
    ├── applet.py
    ├── collectors.py
    ├── _support.py
    ├── README.md
    ├── QA.md
    ├── tests/
    │   ├── test_audit_regressions.py
    │   ├── test_collectors.py
    │   ├── test_release_contract.py
    │   └── test_view_placement.py
    └── icon.png
```

`applet.json` defines the applet's LinSpectacles identity and integration metadata. `standalone.py` provides direct standalone launching, while the applet entrypoint allows the same inspector to run inside LinSpectacles Hub.

## Configuration

Display Server Inspector persists presentation state implemented by the applet, including current view, Metadata Details visibility/layout and per-view column widths/visibility where implemented.

Persisted UI state does not change display-server, compositor or output configuration.

## Scope

Display Server Inspector owns **graphical-session and display-stack evidence**.

GPU/DRM device, client, memory and engine inspection belongs to **GPU Inspector**. Broader PCI/NUMA/IOMMU structure belongs to **Hardware Topology**. Login/session-manager state outside the graphical-display question remains the responsibility of **Login Inspector**.

## License

GNU General Public License v3.0 or later. See [`LICENSE`](LICENSE).

## Links

- LinSpectacles organisation: <https://github.com/linspectacles/>
- LinSpectacles Hub: <https://github.com/linspectacles/linspectacles-hub>
- Repository: <https://github.com/linspectacles/display-server>
- Issues: <https://github.com/linspectacles/display-server/issues>

<p align="center">
  <a href="https://github.com/linspectacles/display-server">
    <img
      src="display_server/icon.png"
      alt="Display Server Inspector"
      width="256"
    >
  </a>
</p>
