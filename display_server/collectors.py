"""Read-only, on-demand graphical-session collection. No shell, no mutation, no polling.

Collector output is evidence-bound: optional output-management APIs are never inferred
from protocol advertisements, and XWayland RandR is never used for physical outputs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VIEWS = ("Session", "Display Stack", "Outputs", "Modes", "Protocols")
COLUMNS = {
    "Session": [("name", "Session"), ("type", "Type"), ("desktop", "Desktop"), ("seat", "Seat"), ("state", "State")],
    "Display Stack": [("name", "Component"), ("role", "Role"), ("process", "Process"), ("pid", "PID"), ("endpoint", "Endpoint"), ("state", "State")],
    "Outputs": [("name", "Output"), ("state", "State"), ("resolution", "Resolution"), ("refresh", "Refresh"), ("scale", "Scale"), ("position", "Position")],
    "Modes": [("output", "Output"), ("resolution", "Resolution"), ("refresh", "Refresh"), ("current", "Current"), ("preferred", "Preferred")],
    "Protocols": [("name", "Interface / Extension"), ("type", "Type"), ("version", "Version"), ("source", "Source")],
}


def record(view: str, key: str, columns: dict, detail: dict, source: str):
    fields = dict(detail)
    fields["Acquisition Source"] = source
    return {"view": view, "id": str(key), "columns": columns, "detail": fields, "source": source}


def display_refresh(value):
    if value is None or value == "":
        return "Not exposed"
    try:
        n = float(value)
        # Both X11 and Mutter/KScreen provide Hz; wlr provides millihertz.
        return f"{n:.3f}".rstrip("0").rstrip(".") + " Hz"
    except (TypeError, ValueError):
        return str(value)


def fmt_pos(value):
    if isinstance(value, dict):
        x = value.get("x")
        y = value.get("y")
        return f"{x},{y}" if x is not None and y is not None else "Not exposed"
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return f"{value[0]},{value[1]}"
    return str(value) if value is not None and value != "" else "Not exposed"


def fmt_size(width, height):
    return f"{width}×{height}" if width is not None and height is not None else "Not exposed"


def _bool_state(value, true="Yes", false="No"):
    if isinstance(value, bool):
        return true if value else false
    return "Not exposed"


def _exe_run(args, timeout=2.5):
    """Only fixed, literal argv is permitted. Output is capped to avoid huge reports."""
    if not shutil.which(args[0]):
        return None, "Tool unavailable: " + args[0]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           check=False, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{args[0]}: {type(exc).__name__}"
    if p.returncode != 0:
        message = (p.stderr or p.stdout).strip().replace("\n", "; ")[:240]
        return None, f"{args[0]}: {message or 'exit ' + str(p.returncode)}"
    if len(p.stdout) > 1_000_000:
        return None, f"{args[0]}: output exceeds 1 MB limit"
    # Xorg / XWayland commonly emit their version banner on stderr.
    return (p.stdout or p.stderr if args[-1] in {'-version', '--version'} else p.stdout), None



# Shared collector/UI sorting semantics; numbers are compared numerically, not lexically.
def inventory_sort_key(column, value):
    text = str(value if value is not None else '').strip()
    if column in {'pid', 'version', 'refresh', 'scale'}:
        number = re.search(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)', text)
        if number and text.lower() not in {'not exposed', 'not reported', 'unknown'}:
            try:
                return (0, float(number.group()), '')
            except ValueError:
                pass
        return (1, 0, text.casefold())
    if column == 'resolution':
        m = re.search(r'(\d+)\s*[×x]\s*(\d+)', text)
        if m:
            return (0, int(m.group(1)) * int(m.group(2)), int(m.group(1)))
        return (1, 0, text.casefold())
    if column == 'position':
        m = re.fullmatch(r'\s*(-?\d+)\s*,\s*(-?\d+)\s*', text)
        if m:
            return (0, int(m.group(1)), int(m.group(2)))
        return (1, 0, text.casefold())
    return (0, text.casefold(), '')


def _detail(value, fallback='Not exposed'):
    """Unpack optional GLib variants without inventing a value."""
    try:
        value = value.unpack() if hasattr(value, 'unpack') else value
    except Exception:
        return fallback
    return value if value is not None else fallback


def _logical_pixels(width, height, scale, transform=None):
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in (width, height, scale)) or scale <= 0:
        return 'Not exposed'
    if isinstance(transform, int) and transform in (1, 3, 5, 7):
        width, height = height, width
    return f'{width / scale:g}×{height / scale:g} (derived)'


def _capability(value, bit):
    """KScreen capability bit: a missing value is not proof of no support."""
    if isinstance(value, int) and not isinstance(value, bool):
        return 'Reported supported' if value & bit else 'Not advertised'
    if isinstance(value, (list, tuple, set)):
        return 'Reported supported' if bit in value else 'Not advertised'
    return 'Not exposed'


def _reported_bool(value):
    if isinstance(value, bool):
        return 'Enabled' if value else 'Disabled'
    return 'Not exposed'


def parse_properties(output):
    result = {}
    for line in (output or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def classify_session(env):
    t = (env.get("XDG_SESSION_TYPE") or "").strip().lower()
    if t in ("wayland", "x11", "tty"):
        return t
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"  # Environment-derived, not proof of a connection.
    if env.get("DISPLAY"):
        return "x11"
    return "unknown"


def _wayland_socket_state(env):
    name = env.get("WAYLAND_DISPLAY", "wayland-0")
    directory = env.get("XDG_RUNTIME_DIR", "")
    if not directory:
        return name, "Runtime directory unavailable"
    # Absolute WAYLAND_DISPLAY paths are permitted by libwayland.
    path = Path(name) if os.path.isabs(name) else Path(directory) / name
    try:
        mode = path.stat().st_mode
        return str(path), "Socket exists" if stat.S_ISSOCK(mode) else "Path is not a socket"
    except OSError:
        return str(path), "Socket not accessible"


def _loginctl_session(env, run):
    """Prefer explicit launch ID, then self; `auto` only if user/type corroborate."""
    fields = ["-p", "Id", "-p", "Type", "-p", "Desktop", "-p", "Seat",
              "-p", "State", "-p", "Remote", "-p", "Leader", "-p", "User"]
    session_id = env.get('XDG_SESSION_ID', '')
    sources = []
    if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', session_id):
        sources.append((session_id, 'Explicit XDG_SESSION_ID'))
    sources.append(('self', 'Current process session'))
    sources.append(('auto', 'logind auto graphical-session fallback'))
    last_error = ''
    for sid, description in sources:
        output, error = run(['loginctl', 'show-session', sid, '--no-pager', *fields])
        props = parse_properties(output)
        if not props.get('Id'):
            last_error = error or 'No session identity returned'
            continue
        uid = props.get('User')
        if uid and str(uid) != str(os.getuid()):
            continue
        if sid == 'auto':
            # Auto can select another session. Never infer a graphical session
            # when this launch environment contains no graphical evidence.
            hint = classify_session(env)
            if hint not in {'wayland', 'x11'} or props.get('Type') != hint:
                continue
            seat = env.get('XDG_SEAT')
            if seat and props.get('Seat') and props['Seat'] != seat:
                continue
        return props, description, ''
    return {}, 'XDG environment only', last_error


def collect_session(env, run=_exe_run):
    t = classify_session(env)
    props, session_source, error = _loginctl_session(env, run) if t != 'tty' else ({}, 'XDG environment only', '')
    reported_type = props.get('Type') or 'Not exposed'
    detected_type = t if t != 'unknown' else (reported_type if reported_type != 'Not exposed' else 'unknown')
    session_id = props.get('Id') or env.get('XDG_SESSION_ID') or ''
    detail = {
        'Session Identifier': session_id or 'Not exposed',
        'Session Type': detected_type,
        'Type Reported by loginctl': reported_type,
        'Type Source': 'XDG_SESSION_TYPE' if env.get('XDG_SESSION_TYPE') else 'Environment or loginctl',
        'Session Lookup': session_source,
        'Session Association Note': ('Auto-selected same-user matching graphical session; not independently linked to the launching process'
                                     if session_source == 'logind auto graphical-session fallback' else 'Explicit or caller-session evidence'
                                     if props else 'No logind association established'),
        'Desktop': props.get('Desktop') or env.get('XDG_CURRENT_DESKTOP') or 'Not exposed',
        'Seat': props.get('Seat') or env.get('XDG_SEAT') or 'Not exposed',
        'State': props.get('State') or 'Not exposed',
        'Remote': props.get('Remote') or 'Not exposed',
        'Leader PID': props.get('Leader') or 'Not exposed',
        'DISPLAY': env.get('DISPLAY') or 'Not set',
        'WAYLAND_DISPLAY': env.get('WAYLAND_DISPLAY') or 'Not set',
        'XDG_RUNTIME_DIR': env.get('XDG_RUNTIME_DIR') or 'Not set',
    }
    if error:
        detail['loginctl'] = error
    row = record('Session', 'session', {
        'name': session_id or 'Current launch environment',
        'type': detected_type, 'desktop': detail['Desktop'],
        'seat': detail['Seat'], 'state': detail['State'],
    }, detail, 'XDG environment' + ('; loginctl show-session' if props else ''))
    stack = []
    if detected_type == 'wayland':
        endpoint, sockstate = _wayland_socket_state(env)
        stack.append(record('Display Stack', 'wayland-endpoint', {
            'name': 'Wayland display', 'role': 'Display socket', 'process': 'Not established',
            'pid': '', 'endpoint': endpoint, 'state': sockstate,
        }, {'Endpoint': endpoint, 'Socket State': sockstate,
            'Ownership': 'Endpoint existence does not identify a compositor'},
            'WAYLAND_DISPLAY; filesystem socket metadata'))
        if env.get('DISPLAY'):
            stack.append(record('Display Stack', 'x11-endpoint', {
                'name': 'X11 endpoint', 'role': 'Potential XWayland transport',
                'process': 'Not established', 'pid': '', 'endpoint': env['DISPLAY'],
                'state': 'Advertised by DISPLAY',
            }, {'Endpoint': env['DISPLAY'],
                'Classification': 'X11 endpoint in Wayland session; XWayland ownership unverified',
                'Warning': 'XWayland RandR is not physical output evidence'},
                'DISPLAY environment in Wayland session'))
    elif detected_type == 'x11':
        stack.append(record('Display Stack', 'x11-endpoint', {
            'name': 'X11 display', 'role': 'X server connection', 'process': 'Not established',
            'pid': '', 'endpoint': env.get('DISPLAY') or 'Not set', 'state': 'Configured',
        }, {'Endpoint': env.get('DISPLAY') or 'Not set'}, 'DISPLAY environment'))
    return row, stack, detected_type


def parse_wayland_info(text):
    """Parse advertised globals and basic wl_output events from wayland-info text.

    wl_output data is partial/possibly virtual. Logical layout is intentionally not
    inferred from raw wl_output x/y; a compositor-specific API is preferred.
    """
    protocols = []
    outputs = []
    modes = []
    current_output = None
    current_mode = None
    for raw in text.splitlines():
        line = raw.strip()
        match = re.match(r"interface:\s*'([^']+)',\s*version:\s*(\d+),\s*name:\s*(\d+)", line)
        if match:
            name, version, global_id = match.groups()
            protocols.append(record("Protocols", f"wl:{global_id}", {
                "name": name, "type": "Wayland global", "version": version, "source": "wayland-info"
            }, {"Interface": name, "Advertised Version": version, "Registry Global": global_id,
                "Interpretation": "Advertised by this compositor; not proof a feature is enabled"},
                "wayland-info / wl_registry"))
            current_output = None
            current_mode = None
            if name == "wl_output":
                current_output = {"registry_id": global_id, "name": f"wl_output #{global_id}",
                                  "model": "Not exposed", "scale": "Not exposed", "position": "Not exposed"}
                outputs.append(current_output)
            continue
        if current_output is None:
            continue
        name_match = re.search(r"\bname:\s*'([^']+)'", line)
        if name_match:
            current_output["name"] = name_match.group(1)
        model_match = re.search(r"\bmodel:\s*'([^']+)'", line)
        if model_match:
            current_output["model"] = model_match.group(1)
        make_match = re.search(r"\bmake:\s*'([^']+)'", line)
        if make_match:
            current_output["make"] = make_match.group(1)
        scale_match = re.search(r"(?:^|,)\s*scale:\s*(\d+)", line)
        if scale_match:
            current_output["scale"] = scale_match.group(1)
        if line.startswith("mode:"):
            current_mode = {"output": current_output, "width": None, "height": None,
                            "refresh": None, "flags": ""}
            modes.append(current_mode)
        if current_mode:
            dim = re.search(r"width:\s*(\d+)\s*px,\s*height:\s*(\d+)\s*px,\s*refresh:\s*([\d.]+)\s*Hz", line)
            if dim:
                current_mode.update(width=int(dim[1]), height=int(dim[2]), refresh=float(dim[3]))
            flags = re.search(r"flags:\s*([\w\s,]+)", line)
            if flags:
                current_mode["flags"] = flags.group(1).strip()
    output_records = []
    for out in outputs:
        owned_modes = [m for m in modes if m["output"] is out]
        active = next((m for m in owned_modes if "current" in m["flags"]), None)
        width = active["width"] if active else None
        height = active["height"] if active else None
        output_records.append(record("Outputs", "wl:" + out["registry_id"], {
            "name": out["name"], "state": "Reported; enablement not exposed",
            "resolution": fmt_size(width, height),
            "refresh": display_refresh(active["refresh"] if active else None),
            "scale": out["scale"], "position": "Not exposed",
        }, {"Registry Global": out["registry_id"], "Model": out.get("model", "Not exposed"),
            "Make": out.get("make", "Not exposed"),
            "Scope": "wl_output protocol; may represent virtual or partial output information",
            "Logical Position": "Not exposed by this collector"}, "wayland-info / wl_output"))
    mode_records = []
    for i, mode in enumerate(modes):
        if mode["width"] is None:
            continue
        flags = mode["flags"]
        mode_records.append(record("Modes", f"wlmode:{mode['output']['registry_id']}:{i}", {
            "output": mode["output"]["name"],
            "resolution": fmt_size(mode["width"], mode["height"]),
            "refresh": display_refresh(mode["refresh"]),
            "current": "Yes" if "current" in flags else "Not reported",
            "preferred": "Yes" if "preferred" in flags else "Not reported",
        }, {"Registry Global": mode["output"]["registry_id"],
            "Flags": flags or "Not exposed"}, "wayland-info / wl_output"))
    return protocols, output_records, mode_records


def parse_xrandr(text):
    outputs, modes = [], []
    current = None
    for line in text.splitlines():
        if not line.startswith(" "):
            m = re.match(r"^(\S+)\s+(connected|disconnected)\b(.*)", line)
            if not m:
                current = None
                continue
            name, status, rest = m.groups()
            primary = "primary" in rest.split()
            dims = re.search(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", rest)
            current = {"name": name, "connected": status == "connected", "primary": primary,
                       "position": f"{int(dims[3])},{int(dims[4])}" if dims else "Not exposed",
                       "resolution": fmt_size(dims[1], dims[2]) if dims else "Not exposed",
                       "refresh": "Not exposed", "modes": [],
                       "rotation": next((v for v in ('normal', 'left', 'right', 'inverted')
                                         if re.search(r'\(' + v + r'\b', rest)), 'Not exposed'),
                       "physical": (lambda m: fmt_size(m[1] + 'mm', m[2] + 'mm') if m else 'Not exposed')(
                           re.search(r'(\d+)mm\s*x\s*(\d+)mm', rest)),
                       "current_mode": rest.strip()}
            outputs.append(current)
            continue
        if current is None:
            continue
        mode_match = re.match(r"^\s+(\d+)x(\d+)\s+(.+)$", line)
        if mode_match:
            w,h, rates = mode_match.groups()
            for i, rate in enumerate(rates.split()):
                r = re.match(r"^(\d+(?:\.\d+)?)([+*i]*)", rate)
                if not r:
                    continue
                val, flags = r.groups()
                current["modes"].append((w, h, val, flags))
                if "*" in flags:
                    current["refresh"] = display_refresh(val)
    output_records = []
    for out in outputs:
        output_records.append(record("Outputs", "x11:" + out["name"], {
            "name": out["name"], "state": "Connected" if out["connected"] else "Disconnected",
            "resolution": out["resolution"], "refresh": out["refresh"],
            "scale": "Not exposed", "position": out["position"],
        }, {"Primary": "Yes" if out["primary"] else "No",
            "Server": "Native X11 session only", "Scale": "Not exposed by xrandr --query",
            "Physical Size": out['physical'], "Rotation": out['rotation'],
            "Native Output Geometry": out['current_mode'],
            "Logical Geometry": out['resolution'] + ' at ' + out['position'] if out['position'] != 'Not exposed' else 'Not exposed'},
            "xrandr --query; native X11"))
        for i, (w, h, rate, flags) in enumerate(out["modes"]):
            modes.append(record("Modes", f"x11:{out['name']}:{i}", {
                "output": out["name"], "resolution": fmt_size(w, h),
                "refresh": display_refresh(rate),
                "current": "Yes" if "*" in flags else "No",
                "preferred": "Yes" if "+" in flags else "Not reported",
            }, {"X11 Mode Flags": flags or "None"}, "xrandr --query; native X11"))
    return output_records, modes


def parse_xdpyinfo(text):
    protocols = []
    capture = False
    for line in text.splitlines():
        if re.match(r"^number of extensions:\s*\d+", line):
            capture = True
            continue
        if capture:
            if line and not line[0].isspace():
                capture = False
                continue
            name = line.strip()
            if name and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{1,100}", name):
                protocols.append(record("Protocols", "x11:" + name, {
                    "name": name, "type": "X11 extension", "version": "Not queried", "source": "xdpyinfo"
                }, {"Advertised": "Yes", "Extension Version": "Not queried"},
                    "xdpyinfo / X11 extension list"))
    return protocols


def _modes_from_json(name, modes_raw, current_id=None, source="", preferred_id=None):
    records, current = [], None
    if isinstance(modes_raw, dict):
        modes_raw = list(modes_raw.values())
    if not isinstance(modes_raw, list):
        return records, None
    for i, mode in enumerate(modes_raw):
        if not isinstance(mode, dict):
            continue
        size = mode.get("size") or {}
        if isinstance(size, dict):
            width = mode.get("width", size.get("width"))
            height = mode.get("height", size.get("height"))
        elif isinstance(size, list) and len(size) >= 2:
            width, height = size[:2]
        else:
            width, height = mode.get("width"), mode.get("height")
        hz = mode.get("refreshRate", mode.get("refresh", mode.get("refresh_rate")))
        if source.startswith("wlr") and isinstance(hz, (float,int)) and hz > 1000:
            hz /= 1000
        mode_id = str(mode.get("id", i))
        is_current = mode.get("current") is True or mode_id == str(current_id) and current_id is not None
        is_preferred = mode.get("preferred") is True or mode_id == str(preferred_id) and preferred_id is not None
        if is_current:
            current = (width, height, hz)
        records.append(record("Modes", f"{source}:{name}:{mode_id}:{i}", {
            "output": name, "resolution": fmt_size(width, height), "refresh": display_refresh(hz),
            "current": "Yes" if is_current else "No",
            "preferred": "Yes" if is_preferred else "Not reported",
        }, {"Mode ID": mode_id}, source))
    return records, current


def parse_kscreen_json(text):
    parsed = json.loads(text)
    raw = parsed.get("outputs", []) if isinstance(parsed, dict) else []
    if isinstance(raw, dict):
        raw = list(raw.values())
    outputs, modes = [], []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("id") or f"Output {i+1}")
        mode_rows, current = _modes_from_json(name, entry.get("modes", []),
                             entry.get("currentModeId"), "kscreen-doctor -j",
                             entry.get("preferredModeId"))
        modes.extend(mode_rows)
        enabled = entry.get("enabled")
        connected = entry.get("connected")
        st = "Enabled" if enabled is True else "Disabled" if enabled is False else "Not exposed"
        if connected is False:
            st += " / disconnected"
        capabilities = entry.get('capabilities')
        transform = entry.get('rotation', 'Not exposed')
        physical = entry.get('sizeMM', entry.get('physicalSize', entry.get('sizeMm')))
        physical_width = physical.get('width') if isinstance(physical, dict) else None
        physical_height = physical.get('height') if isinstance(physical, dict) else None
        # KScreen documented Output::Capability bits: VRR=2, HDR=8, WCG=16.
        logical_value = entry.get('explicitLogicalSize')
        if isinstance(logical_value, dict) and isinstance(logical_value.get('width'), (int, float)) and isinstance(logical_value.get('height'), (int, float)):
            logical_size = fmt_size(logical_value['width'], logical_value['height']) + ' (reported)'
        else:
            logical_size = _logical_pixels(current[0], current[1], entry.get('scale'),
                        1 if transform in (2, 8, 32, 128, 'left', 'right') else 0) if current else 'Not exposed'
        detail = {"Connection": _bool_state(connected, "Connected", "Disconnected"),
                  "Enabled": _bool_state(enabled),
                  "Model": entry.get("model") or "Not exposed",
                  "Rotation": transform, "Primary": _bool_state(entry.get("primary")),
                  "Physical Size": fmt_size(physical_width, physical_height) + ' mm' if physical_width is not None and physical_height is not None else 'Not exposed',
                  "Logical Size": logical_size,
                  "HDR Capability": _capability(capabilities, 8),
                  "HDR Enabled": _reported_bool(entry.get('hdrEnabled', entry.get('hdrEnabledState'))),
                  "VRR Capability": _capability(capabilities, 2),
                  "VRR Policy (reported)": (
                      {0: 'Never', 1: 'Always', 2: 'Automatic'}.get(entry['vrrPolicy'], entry['vrrPolicy'])
                      if isinstance(entry.get('vrrPolicy'), int) else entry.get('vrrPolicy', 'Not exposed')),
                  "VRR Currently Active": 'Not exposed (policy is not an activity measurement)', 
                  "Wide Color Gamut Capability": _capability(capabilities, 16),
                  "Color Profile": entry.get('iccProfilePath', entry.get('colorProfile', 'Not exposed')),
                  "WCG Enabled": _reported_bool(entry.get('wcgEnabled')),
                  "Reported Capabilities": capabilities if capabilities is not None else 'Not exposed'}
        outputs.append(record("Outputs", f"kde:{name}", {
            "name": name, "state": st,
            "resolution": fmt_size(current[0], current[1]) if current else "Not exposed",
            "refresh": display_refresh(current[2]) if current else "Not exposed",
            "scale": entry.get("scale", "Not exposed"),
            "position": fmt_pos(entry.get("pos", entry.get("position"))),
        }, detail, "kscreen-doctor -j / KScreen"))
    return outputs, modes


def parse_wlr_json(text):
    parsed = json.loads(text)
    raw = parsed.get("outputs", []) if isinstance(parsed, dict) else parsed
    if not isinstance(raw, list):
        return [], []
    outputs, modes = [], []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or f"Output {i+1}")
        current_mode = entry.get("current_mode") or entry.get("currentMode")
        modes_raw = [dict(m) for m in entry.get("modes", []) if isinstance(m, dict)]
        for m in modes_raw:
            if isinstance(current_mode, dict):
                m["current"] = (m.get("width"), m.get("height"), m.get("refresh")) == (
                    current_mode.get("width"), current_mode.get("height"), current_mode.get("refresh"))
        mode_rows, current = _modes_from_json(name, modes_raw, None, "wlr-randr --json")
        modes.extend(mode_rows)
        enabled = entry.get("enabled")
        position = entry.get("position")
        if position is None and "x" in entry and "y" in entry:
            position = [entry["x"], entry["y"]]
        outputs.append(record("Outputs", f"wlr:{name}", {
            "name": name, "state": "Enabled" if enabled is True else "Disabled" if enabled is False else "Not exposed",
            "resolution": fmt_size(current[0], current[1]) if current else "Not exposed",
            "refresh": display_refresh(current[2]) if current else "Not exposed",
            "scale": entry.get("scale", "Not exposed"), "position": fmt_pos(position),
        }, {"Description": entry.get("description", "Not exposed"),
            "Transform": entry.get("transform", "Not exposed"),
            "Adaptive Sync": entry.get("adaptive_sync", "Not exposed"),
            "VRR Current State": _reported_bool(entry.get('adaptive_sync')),
            "Physical Size": fmt_size(entry.get('physical_width'), entry.get('physical_height')) + ' mm' if entry.get('physical_width') is not None and entry.get('physical_height') is not None else 'Not exposed',
            "Logical Size": _logical_pixels(current[0], current[1], entry.get('scale')) if current else 'Not exposed',
            "HDR Capability": 'Not exposed', "HDR Enabled": 'Not exposed'},
            "wlr-randr --json / output-management protocol"))
    return outputs, modes


def parse_mutter_state(data):
    """Parse GetCurrentState without turning connected monitors into enabled ones."""
    monitors, logicals = data[1], data[2]
    logical_by_connector = {}
    for logical in logicals:
        try:
            x, y, scale, transform, primary, specs, properties = logical
            for spec in specs:
                logical_by_connector[str(spec[0])] = {
                    'pos': (x, y), 'scale': scale, 'transform': transform,
                    'primary': primary,
                    'properties': _detail(properties, {}),
                }
        except (ValueError, TypeError, IndexError):
            continue
    outputs, modes = [], []
    for mon in monitors:
        try:
            spec, mode_items, properties = mon
            connector, vendor, product, serial = spec
        except (TypeError, ValueError):
            continue
        connector = str(connector)
        monprops = {k: _detail(v) for k, v in dict(properties).items()}
        current = None
        for entry in mode_items:
            try:
                mode_id, width, height, refresh, preferred_scale, scales, props = entry
                props = {k: _detail(v) for k, v in dict(props).items()}
            except (TypeError, ValueError):
                continue
            is_current = props.get('is-current') is True
            is_preferred = props.get('is-preferred') is True
            if is_current:
                current = (mode_id, width, height, refresh)
            modes.append(record('Modes', f'gnome:{connector}:{mode_id}', {
                'output': connector, 'resolution': fmt_size(width, height),
                'refresh': display_refresh(refresh),
                'current': 'Yes' if is_current else 'No',
                'preferred': 'Yes' if is_preferred else 'No',
            }, {'Mode ID': mode_id, 'Preferred Scale': preferred_scale,
                'Supported Scales': ', '.join(str(v) for v in scales),
                'Interlaced': _bool_state(props.get('is-interlaced'))},
                'Mutter DisplayConfig.GetCurrentState'))
        logical = logical_by_connector.get(connector)
        # Connected monitors with no logical-monitor membership are disabled
        # in Mutter's current layout; do not describe them as merely 'reported'.
        enabled = logical is not None
        geom = 'Not exposed'
        if enabled and current:
            geom = _logical_pixels(current[1], current[2], logical['scale'], logical['transform'])
        width_mm, height_mm = monprops.get('width-mm'), monprops.get('height-mm')
        output_details = {
            'Vendor': vendor or 'Not exposed', 'Product': product or 'Not exposed',
            'Serial': serial or 'Not exposed', 'Connection': 'Reported connected by Mutter',
            'Enabled': 'Yes' if enabled else 'No',
            'Primary': _bool_state(logical['primary']) if enabled else 'No',
            'Rotation / Transform Enum': logical['transform'] if enabled else 'Not exposed',
            'Physical Size': f'{width_mm}×{height_mm} mm' if isinstance(width_mm, int) and isinstance(height_mm, int) else 'Not exposed',
            'Logical Size': geom,
            'Logical Position': fmt_pos(logical['pos']) if enabled else 'Not exposed',
            'Display Name': monprops.get('display-name', 'Not exposed'),
            'Underscanning': _bool_state(monprops.get('is-underscanning')),
            'HDR Capability': ('Reported supported' if _detail(monprops.get('supports-hdr')) is True else
                               'Not advertised' if _detail(monprops.get('supports-hdr')) is False else 'Not exposed'),
            'HDR Enabled': _reported_bool(_detail(monprops.get('is-hdr-enabled'))),
            'VRR Capability': ('Reported supported' if _detail(monprops.get('supports-vrr')) is True else
                               'Not advertised' if _detail(monprops.get('supports-vrr')) is False else 'Not exposed'),
            'Supported Color Modes': monprops.get('supported-color-modes', 'Not exposed'),
            'Current Color Mode': (logical.get('properties', {}).get('color-mode', 'Not exposed')
                                   if enabled and isinstance(logical.get('properties'), dict)
                                   else 'Not exposed'),
        }
        outputs.append(record('Outputs', f'gnome:{connector}', {
            'name': connector, 'state': 'Enabled' if enabled else 'Disabled (connected)',
            'resolution': fmt_size(current[1], current[2]) if current else 'Not exposed',
            'refresh': display_refresh(current[3]) if current else 'Not exposed',
            'scale': logical['scale'] if enabled else 'Not exposed',
            'position': fmt_pos(logical['pos']) if enabled else 'Not exposed',
        }, output_details, 'Mutter DisplayConfig.GetCurrentState'))
    return outputs, modes


def collect_mutter_gio():
    """GNOME read-only current state; optional GI, no D-Bus setting operations."""
    try:
        import gi
        gi.require_version('Gio', '2.0')
        from gi.repository import Gio
    except (ImportError, ValueError):
        return None, 'Mutter GObject binding unavailable (python3-gobject)'
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        resp = bus.call_sync('org.gnome.Mutter.DisplayConfig',
                             '/org/gnome/Mutter/DisplayConfig',
                             'org.gnome.Mutter.DisplayConfig', 'GetCurrentState',
                             None, None, Gio.DBusCallFlags.NONE, 2500, None)
        return parse_mutter_state(resp.unpack()), None
    except Exception as exc:
        return None, f'Mutter DisplayConfig unavailable: {type(exc).__name__}'


# A process name and matching UID cannot establish ownership of an active session.
# Use explicit logind session evidence or the Unix display socket's inode.
_PROCESS_ROLES = {
    'gnome-shell': 'Compositor', 'kwin_wayland': 'Compositor',
    'kwin_x11': 'Window manager', 'sway': 'Compositor',
    'Hyprland': 'Compositor', 'labwc': 'Compositor',
    'wayfire': 'Compositor', 'weston': 'Compositor',
    'Xwayland': 'XWayland server', 'Xorg': 'X server',
    'X': 'X server', 'cage': 'Compositor',
}
_VERSION_ARGS = {
    'gnome-shell': ['gnome-shell', '--version'],
    'kwin_wayland': ['kwin_wayland', '--version'],
    'kwin_x11': ['kwin_x11', '--version'],
    'sway': ['sway', '--version'],
    'Hyprland': ['Hyprland', '--version'],
    'labwc': ['labwc', '--version'],
    'wayfire': ['wayfire', '--version'],
    'weston': ['weston', '--version'],
    'Xwayland': ['Xwayland', '-version'],
    'Xorg': ['Xorg', '-version'],
}


def _display_unix_paths(env):
    paths = {}
    if classify_session(env) == 'wayland':
        wayland, _ = _wayland_socket_state(env)
        paths[wayland] = 'Wayland display socket'
    display = env.get('DISPLAY', '')
    m = re.fullmatch(r':(\d+)(?:\.\d+)?', display)
    if m:
        for prefix in ('/tmp/.X11-unix/', '@/tmp/.X11-unix/'):
            paths[prefix + 'X' + m.group(1)] = 'X11 display socket'
    return paths


def _unix_socket_inodes(paths, unix_file='/proc/net/unix'):
    results = {}
    try:
        with open(unix_file, encoding='utf-8', errors='replace') as stream:
            for line in stream:
                parts = line.strip().split(maxsplit=7)
                if len(parts) == 8 and parts[-1] in paths and parts[6].isdigit():
                    results[parts[6]] = paths[parts[-1]]
    except OSError:
        pass
    return results


def _process_info(path):
    """Only Linux /proc introspection; a failure means absence of evidence."""
    env = {}
    try:
        raw = (path / 'environ').read_bytes()[:131072]
        env = dict(item.decode('utf-8', 'replace').split('=', 1)
                   for item in raw.split(b'\x00') if b'=' in item)
    except (OSError, ValueError):
        pass
    try:
        argv = [v.decode('utf-8', 'replace') for v in
                (path / 'cmdline').read_bytes()[:65536].split(b'\x00') if v]
    except OSError:
        argv = []
    try:
        cgroup = (path / 'cgroup').read_text(errors='replace')[:32768]
    except OSError:
        cgroup = ''
    return env, argv, cgroup


def _socket_owner(path, inode_ids):
    if not inode_ids:
        return None
    try:
        for fd in (path / 'fd').iterdir():
            try:
                link = os.readlink(fd)
                if link.startswith('socket:[') and link[8:-1] in inode_ids:
                    return inode_ids[link[8:-1]]
            except OSError:
                continue
    except OSError:
        pass
    return None


def _component_version(name, run, executable=None):
    args = _VERSION_ARGS.get(name)
    # Invoke only the exact running executable from a recognised system
    # directory, not a similarly named command somewhere earlier in PATH.
    if not args or not executable:
        return 'Not exposed'
    safe_roots = ('/usr/bin/', '/usr/libexec/', '/usr/lib/', '/bin/')
    if not executable.startswith(safe_roots) or os.path.basename(executable) != name:
        return 'Not exposed'
    result, error = run([executable, args[-1]])
    if result:
        line = next((line.strip() for line in result.splitlines()
                     if re.search(r'\b\d+\.\d+(?:\.\d+)?\b', line)), '')
        return line[:160] if line else 'Not exposed'
    return 'Not exposed'


def collect_proc_candidates(env, run=_exe_run, session_id=None, proc_root='/proc',
                            unix_file='/proc/net/unix'):
    """Include processes only when session or socket ownership is corroborated.

    Explicit mismatches are excluded. A matching login session proves membership,
    not compositor ownership; only Unix socket fd evidence proves endpoint owner.
    """
    found = []
    paths = _display_unix_paths(env)
    inodes = _unix_socket_inodes(paths, unix_file)
    valid_id = session_id if session_id and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', str(session_id)) else None
    try:
        children = list(Path(proc_root).iterdir())
    except OSError:
        return found
    for path in children:
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            name = (path / 'comm').read_text(errors='replace').strip()
            if name not in _PROCESS_ROLES:
                continue
            pid = int(path.name)
            procenv, argv, cgroup = _process_info(path)
            other_id = procenv.get('XDG_SESSION_ID')
            if valid_id and other_id and other_id != valid_id:
                continue  # Known other session; never show it as a candidate.
            owner = _socket_owner(path, inodes)
            # X server attribution needs its X11 socket, not an unrelated
            # Wayland socket inadvertently owned by the same process.
            if name in {'Xwayland', 'Xorg', 'X'} and owner != 'X11 display socket':
                owner = None
            session_match = bool(valid_id and (other_id == valid_id or
                re.search(r'(?<![A-Za-z0-9_.-])session-' + re.escape(valid_id) + r'\.scope(?:/|$)', cgroup)))
            # Do not include unrelated same-user processes merely by name.
            if not owner and not session_match:
                continue
            endpoint = owner or 'Not established'
            verified = bool(owner)
            evidence = ('Owns the current ' + owner if verified else
                        'Matching login session; socket ownership not established')
            if name == 'Xwayland' and not owner:
                # A same-session XWayland process is not enough to bind it to
                # DISPLAY; require explicit matching X11 display argument.
                if env.get('DISPLAY') not in argv:
                    continue
                evidence = 'Matching login session and exact DISPLAY argument'
            if name in {'X', 'Xorg'} and not owner and env.get('DISPLAY') not in argv:
                continue
            try:
                exe_path = os.readlink(path / 'exe')
            except OSError:
                exe_path = None
            version = _component_version(name, run, exe_path) if (verified or session_match) else 'Not exposed'
            found.append(record('Display Stack', f'proc:{pid}', {
                'name': name, 'role': _PROCESS_ROLES[name], 'process': name,
                'pid': str(pid), 'endpoint': endpoint,
                'state': 'Endpoint verified' if verified else 'Session associated',
            }, {'Process Name': name, 'PID': pid, 'UID': os.getuid(),
                'Executable': exe_path or 'Not exposed',
                'Version': version, 'Association': evidence,
                'Command Line': ' '.join(argv)[:800] if argv else 'Not exposed',
                'Session Identifier': valid_id or 'Not exposed',
                'Scope': 'Verified endpoint owner' if verified else 'Session-associated process; server ownership unverified'},
                'read-only /proc and /proc/net/unix' + ('; running executable version flag' if version != 'Not exposed' else '')))
        except (OSError, ValueError):
            continue
    return sorted(found, key=lambda rec: int(rec['columns']['pid']))


def collect_snapshot(env=None, run=_exe_run, mutter=collect_mutter_gio, include_processes=True):
    """Produce a self-contained snapshot; callers trigger this explicitly."""
    env = dict(os.environ if env is None else env)
    data = {v: [] for v in VIEWS}
    diagnostics = []
    session, stack, kind = collect_session(env, run=run)
    data["Session"] = [session]
    data["Display Stack"].extend(stack)
    if include_processes:
        session_detail = session['detail']
        sid = session_detail.get('Session Identifier')
        # The logind `auto` fallback is not sufficient to prove another
        # process's membership in the caller's actual graphical session.
        if session_detail.get('Session Lookup') == 'logind auto graphical-session fallback':
            sid = env.get('XDG_SESSION_ID')
        data['Display Stack'].extend(collect_proc_candidates(env, run=run, session_id=sid))
        xwayland = next((r for r in data['Display Stack'] if
                         r['columns']['name'] == 'Xwayland'), None)
        if xwayland:
            for endpoint in data['Display Stack']:
                if endpoint['id'] == 'x11-endpoint':
                    endpoint['columns']['process'] = 'Xwayland'
                    endpoint['columns']['pid'] = xwayland['columns']['pid']
                    endpoint['columns']['state'] = xwayland['columns']['state']
                    endpoint['detail']['Classification'] = ('XWayland associated with the active X11 endpoint: ' +
                        xwayland['detail']['Association'])
                    endpoint['source'] += '; /proc process corroboration'
                    endpoint['detail']['Acquisition Source'] = endpoint['source']
        elif kind == 'wayland' and env.get('DISPLAY'):
            diagnostics.append('X11 endpoint reported in Wayland session; XWayland ownership not verified')
    if kind == "wayland":
        result, error = run(["wayland-info"])
        wayland_info_ok = result is not None
        if result is not None:
            proto, basic_outputs, basic_modes = parse_wayland_info(result)
            data["Protocols"] = proto
            data["Display Stack"].append(record("Display Stack", "wayland-verified", {
                "name": "Wayland server", "role": "Protocol connection", "process": "Not established",
                "pid": "", "endpoint": env.get("WAYLAND_DISPLAY", "wayland-0"),
                "state": "Connection verified",
            }, {"Connection": "wayland-info successfully queried registry",
                "Compositor Identity": "Not established by registry listing"}, "wayland-info"))
            data["Outputs"], data["Modes"] = basic_outputs, basic_modes
        else:
            diagnostics.append(error)
        # Prefer compositor-specific, read-only output APIs over partial wl_output.
        desktop = (env.get("XDG_CURRENT_DESKTOP") or "").lower()
        candidates = []
        if "gnome" in desktop:
            try:
                gnome_data, err = mutter()
            except Exception as exc:
                gnome_data, err = None, f"Mutter collector error: {type(exc).__name__}"
            if gnome_data and gnome_data[0]:
                candidates.append(("Mutter", gnome_data))
                data['Display Stack'].append(record('Display Stack', 'mutter-service', {
                    'name': 'Mutter DisplayConfig', 'role': 'Compositor display service',
                    'process': 'Not established', 'pid': '',
                    'endpoint': 'Session D-Bus', 'state': 'GetCurrentState succeeded',
                }, {'Service': 'org.gnome.Mutter.DisplayConfig',
                    'Compositor Implementation': 'Mutter interface responding',
                    'Process Identity': 'Not verified by D-Bus call alone'},
                    'Read-only session D-Bus GetCurrentState'))
            elif err:
                diagnostics.append(err)
        # Do not invoke compositor-specific tools purely on existence if the
        # declared desktop does not match; avoid cross-session attribution.
        if "kde" in desktop or "plasma" in desktop:
            result, error = run(["kscreen-doctor", "-j"])
            if result is not None:
                try:
                    parsed = parse_kscreen_json(result)
                    if parsed[0]:
                        candidates.append(("KScreen", parsed))
                        data['Display Stack'].append(record('Display Stack', 'kscreen-service', {
                            'name': 'KScreen', 'role': 'Display configuration interface',
                            'process': 'Not established', 'pid': '',
                            'endpoint': 'KScreen', 'state': 'Output query succeeded',
                        }, {'Compositor Identity': 'Not established by KScreen alone'},
                            'kscreen-doctor -j'))
                except (ValueError, TypeError, KeyError) as exc:
                    diagnostics.append("kscreen-doctor JSON could not be interpreted")
            else:
                diagnostics.append(error)
        # This protocol is permitted only when advertised; suppress errors for
        # unsupported desktops rather than treating them as missing capability.
        advertised_wlr = any(p["columns"]["name"] == "zwlr_output_manager_v1"
                             for p in data["Protocols"])
        # If wayland-info is missing or cannot connect, querying wlr-randr
        # itself is still a valid read-only probe. Success provides authority.
        attempt_wlr = advertised_wlr or (not wayland_info_ok and not candidates)
        if attempt_wlr:
            result, error = run(["wlr-randr", "--json"])
            if result is not None:
                try:
                    parsed = parse_wlr_json(result)
                    if parsed[0]:
                        candidates.append(("wlr", parsed))
                except (ValueError, TypeError, KeyError):
                    diagnostics.append("wlr-randr JSON could not be interpreted")
            else:
                diagnostics.append(error)
        if candidates:
            name, (outputs, modes) = candidates[0]
            data["Outputs"], data["Modes"] = outputs, modes
            diagnostics.append("Output authority: " + name + "; alternative sources not merged")
        elif data["Outputs"]:
            diagnostics.append("Output authority: basic wl_output; partial/possibly virtual information")
        else:
            diagnostics.append("Wayland output inventory not exposed by available ordinary-user sources")
    elif kind == "x11":
        # In an actual X11 session, xrandr is a valid view of X server outputs.
        result, err = run(["xrandr", "--query"])
        if result is not None:
            data["Outputs"], data["Modes"] = parse_xrandr(result)
        else:
            diagnostics.append(err)
        result, err = run(["xdpyinfo"])
        if result is not None:
            data["Protocols"] = parse_xdpyinfo(result)
        else:
            diagnostics.append(err)
    else:
        diagnostics.append("No native graphical-session type established; no compositor probes run")
    empty_reasons = {}
    for view in VIEWS:
        if data[view]:
            continue
        if kind not in {'wayland', 'x11'}:
            empty_reasons[view] = 'No supported graphical-session connection established'
        elif view == 'Outputs':
            empty_reasons[view] = 'Display outputs not exposed by available session sources'
        elif view == 'Modes':
            empty_reasons[view] = 'Display modes not exposed by available session sources'
        elif view == 'Protocols':
            empty_reasons[view] = 'Graphical protocol information unavailable from accessible sources'
        else:
            empty_reasons[view] = 'No records reported by accessible session sources'
    return {'data': data, 'diagnostics': [d for d in diagnostics if d],
            'empty_reasons': empty_reasons, 'session_type': kind,
            'acquired': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}
