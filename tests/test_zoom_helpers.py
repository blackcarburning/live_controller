"""Tests for the pure-Python zoom/composite helper functions in live_controller.py.

These helpers contain no PyQt dependencies, so they can be tested without a
display or Qt application instance.  The helpers are re-implemented verbatim
here rather than imported from live_controller (which has PyQt top-level
imports that would fail in headless CI).
"""

import json
import os
import time
import uuid

# ---------------------------------------------------------------------------
# Verbatim copy of the standalone helpers — keep in sync with live_controller.py
# ---------------------------------------------------------------------------

NUM_ZONES = 5


def _default_zone():
    return {
        "enabled": False,
        "crop_x": 0, "crop_y": 0, "crop_w": 1920, "crop_h": 1080,
        "scale_w": -1, "scale_h": -1,
        "border_px": 0,
        "offset_y": 0,
        "mode": "crop",
    }


def _migrate_zoom_config(cfg):
    def _backfill_composite(d):
        d.setdefault("out_w", -1)
        d.setdefault("out_h", -1)
        d.setdefault("out_sim_enabled", False)
        d.setdefault("comp_crop_x", 0)
        d.setdefault("comp_crop_y", 0)
        d.setdefault("comp_crop_w", 0)
        d.setdefault("comp_crop_h", 0)
        d.setdefault("comp_scale_w", -1)
        d.setdefault("comp_scale_h", -1)

    if not cfg:
        zones = [_default_zone() for _ in range(NUM_ZONES)]
        zones[0]["enabled"] = True
        result = {"zones": zones, "stack_direction": "horizontal",
                  "frame_snapshot_path": "",
                  "out_w": 1920, "out_h": 1080, "out_sim_enabled": False,
                  "comp_crop_x": 0, "comp_crop_y": 0,
                  "comp_crop_w": 0, "comp_crop_h": 0,
                  "comp_scale_w": -1, "comp_scale_h": -1}
        return result
    if "zones" in cfg:
        zones = list(cfg["zones"])
        while len(zones) < NUM_ZONES:
            zones.append(_default_zone())
        for z in zones:
            z.setdefault("border_px", 0)
            z.setdefault("offset_y", 0)
            z.setdefault("mode", "crop")
        result = {
            "zones": zones[:NUM_ZONES],
            "stack_direction": cfg.get("stack_direction", "horizontal"),
            "frame_snapshot_path": cfg.get("frame_snapshot_path", ""),
        }
        for k in ("out_w", "out_h", "out_sim_enabled",
                  "comp_crop_x", "comp_crop_y", "comp_crop_w", "comp_crop_h",
                  "comp_scale_w", "comp_scale_h"):
            if k in cfg:
                result[k] = cfg[k]
        _backfill_composite(result)
        return result
    # Old single-zone format
    zone0 = {
        "enabled": cfg.get("enabled", True),
        "crop_x": cfg.get("crop_x", 0),
        "crop_y": cfg.get("crop_y", 0),
        "crop_w": cfg.get("crop_w", 1920),
        "crop_h": cfg.get("crop_h", 1080),
        "scale_w": cfg.get("scale_w", -1),
        "scale_h": cfg.get("scale_h", -1),
        "border_px": 0,
        "offset_y": 0,
        "mode": "crop",
    }
    zones = [zone0] + [_default_zone() for _ in range(NUM_ZONES - 1)]
    result = {"zones": zones, "stack_direction": "horizontal", "frame_snapshot_path": ""}
    _backfill_composite(result)
    return result


def _build_vf_for_zones(zoom_config):
    if not zoom_config:
        return None
    if "zones" not in zoom_config:
        if not zoom_config.get("enabled"):
            return None
    migrated = _migrate_zoom_config(zoom_config)
    zones = migrated.get("zones", [])
    direction = migrated.get("stack_direction", "horizontal")
    enabled = [z for z in zones if z.get("enabled") and z.get("crop_w", 0) > 0]
    if not enabled:
        return None

    def _zone_vf(z):
        vf = f"crop={z['crop_w']}:{z['crop_h']}:{z['crop_x']}:{z['crop_y']}"
        sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
        if sw > 0 and sh > 0:
            vf += f",scale={sw}:{sh}"
        border = z.get("border_px", 0)
        if border > 0:
            vf += f",pad=iw+{2*border}:ih+{2*border}:{border}:{border}:black"
        offset_y = int(z.get("offset_y", 0))
        if offset_y != 0:
            abs_offset = abs(offset_y)
            pad_y = max(offset_y, 0)
            crop_y = max(-offset_y, 0)
            vf += f",pad=iw:ih+{abs_offset}:0:{pad_y}:black,crop=iw:ih:0:{crop_y}"
        return vf

    def _zone_out_size(z):
        sw, sh = z.get("scale_w", -1), z.get("scale_h", -1)
        w = sw if sw > 0 else z["crop_w"]
        h = sh if sh > 0 else z["crop_h"]
        border = z.get("border_px", 0)
        return w + 2 * border, h + 2 * border

    comp_crop_w = int(migrated.get("comp_crop_w", 0))
    comp_crop_h = int(migrated.get("comp_crop_h", 0))
    comp_crop_x = int(migrated.get("comp_crop_x", 0))
    comp_crop_y = int(migrated.get("comp_crop_y", 0))
    comp_scale_w = int(migrated.get("comp_scale_w", -1))
    comp_scale_h = int(migrated.get("comp_scale_h", -1))
    out_w = int(migrated.get("out_w", -1))
    out_h = int(migrated.get("out_h", -1))
    out_sim_enabled = bool(migrated.get("out_sim_enabled", False))

    def _composite_suffix():
        parts = []
        if comp_crop_w > 0 and comp_crop_h > 0:
            parts.append(f"crop={comp_crop_w}:{comp_crop_h}:{comp_crop_x}:{comp_crop_y}")
        if comp_scale_w > 0 and comp_scale_h > 0:
            parts.append(f"scale={comp_scale_w}:{comp_scale_h}")
        if out_sim_enabled and out_w > 0 and out_h > 0:
            parts.append(f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black")
        return "," + ",".join(parts) if parts else ""

    if len(enabled) == 1:
        return f"lavfi=[{_zone_vf(enabled[0])}{_composite_suffix()},setsar=1]"

    n = len(enabled)
    zone_sizes = [_zone_out_size(z) for z in enabled]
    if direction == "horizontal":
        target_h = max(s[1] for s in zone_sizes)
    else:
        target_w = max(s[0] for s in zone_sizes)

    split_tags = "".join(f"[z{i}]" for i in range(n))
    split_part = f"split={n}{split_tags}"

    def _zone_segment(z, size, i):
        vf_str = _zone_vf(z)
        out_w_z, out_h_z = size
        if direction == "horizontal" and out_h_z < target_h:
            vf_str += f",pad=iw:{target_h}:0:0:black"
        elif direction == "vertical" and out_w_z < target_w:
            vf_str += f",pad={target_w}:ih:0:0:black"
        return f"[z{i}]{vf_str}[c{i}]"

    crop_parts = [_zone_segment(z, zone_sizes[i], i) for i, z in enumerate(enabled)]
    stack_inputs = "".join(f"[c{i}]" for i in range(n))
    stack_fn = "vstack" if direction == "vertical" else "hstack"
    stack_part = f"{stack_inputs}{stack_fn}=inputs={n}{_composite_suffix()},setsar=1"
    graph = ";".join([split_part] + crop_parts + [stack_part])
    return f"lavfi=[{graph}]"


def _make_unique_mpv_pipe_name(prefix):
    return fr'\\.\pipe\{prefix}_{os.getpid()}_{uuid.uuid4().hex}'


def _send_mpv_ipc_command(ipc_path, command, max_attempts=2, retry_delay=0.05):
    if not ipc_path:
        return False, "Missing IPC pipe path."
    payload = json.dumps({"command": command}, ensure_ascii=False) + "\n"
    last_error = "Unknown IPC error."
    attempts = max(1, max_attempts)
    for i in range(attempts):
        try:
            with open(ipc_path, "w", encoding="utf-8") as f:
                f.write(payload)
            return True, ""
        except Exception as exc:
            last_error = str(exc)
            if i < attempts - 1:
                time.sleep(retry_delay)
    return False, last_error


def _ext_preview_vf_command(vf_str):
    if vf_str:
        return ["vf", "set", vf_str]
    return ["vf", "clr", ""]


# ---------------------------------------------------------------------------
# _migrate_zoom_config tests
# ---------------------------------------------------------------------------

def test_migrate_empty_returns_all_zones():
    result = _migrate_zoom_config({})
    assert len(result["zones"]) == NUM_ZONES
    assert result["zones"][0]["enabled"] is True
    assert all(not z["enabled"] for z in result["zones"][1:])


def test_migrate_empty_includes_composite_fields():
    result = _migrate_zoom_config({})
    assert result["out_w"] == 1920
    assert result["out_h"] == 1080
    assert result["out_sim_enabled"] is False
    assert result["comp_crop_w"] == 0
    assert result["comp_scale_w"] == -1


def test_migrate_old_single_zone_format():
    old = {"enabled": True, "crop_x": 10, "crop_y": 20,
           "crop_w": 960, "crop_h": 540, "scale_w": -1, "scale_h": -1}
    result = _migrate_zoom_config(old)
    z0 = result["zones"][0]
    assert z0["enabled"] is True
    assert z0["crop_x"] == 10
    assert z0["crop_w"] == 960
    # Legacy-compat: out_w=-1 (no padding applied to mpv)
    assert result["out_w"] == -1
    assert result["out_h"] == -1
    assert result["out_sim_enabled"] is False


def test_migrate_existing_zones_backfills_composite_no_op():
    """Configs that have 'zones' but no composite fields get backward-compatible no-ops."""
    cfg = {
        "zones": [{"enabled": True, "crop_x": 0, "crop_y": 0,
                   "crop_w": 1920, "crop_h": 1080, "scale_w": -1, "scale_h": -1}],
        "stack_direction": "horizontal",
    }
    result = _migrate_zoom_config(cfg)
    assert result["out_w"] == -1        # no-op for legacy configs
    assert result["out_h"] == -1
    assert result["out_sim_enabled"] is False
    assert result["comp_crop_w"] == 0   # no composite crop
    assert result["comp_scale_w"] == -1


def test_migrate_preserves_existing_composite_fields():
    cfg = {
        "zones": [{"enabled": True, "crop_x": 0, "crop_y": 0,
                   "crop_w": 1920, "crop_h": 1080, "scale_w": -1, "scale_h": -1}],
        "stack_direction": "horizontal",
        "out_w": 3840, "out_h": 2160, "out_sim_enabled": True,
        "comp_crop_x": 10, "comp_crop_y": 5,
        "comp_crop_w": 1900, "comp_crop_h": 1070,
        "comp_scale_w": 1280, "comp_scale_h": 720,
    }
    result = _migrate_zoom_config(cfg)
    assert result["out_w"] == 3840
    assert result["out_h"] == 2160
    assert result["out_sim_enabled"] is True
    assert result["comp_crop_w"] == 1900
    assert result["comp_scale_h"] == 720


def test_migrate_pads_zones_to_num_zones():
    cfg = {
        "zones": [{"enabled": True, "crop_x": 0, "crop_y": 0,
                   "crop_w": 640, "crop_h": 360, "scale_w": -1, "scale_h": -1}],
        "stack_direction": "vertical",
    }
    result = _migrate_zoom_config(cfg)
    assert len(result["zones"]) == NUM_ZONES


def test_migrate_backfills_zone_fields():
    cfg = {
        "zones": [{"enabled": True, "crop_x": 0, "crop_y": 0,
                   "crop_w": 1280, "crop_h": 720}],  # No border_px / offset_y / mode
    }
    result = _migrate_zoom_config(cfg)
    z = result["zones"][0]
    assert z["border_px"] == 0
    assert z["offset_y"] == 0
    assert z["mode"] == "crop"


# ---------------------------------------------------------------------------
# _build_vf_for_zones tests
# ---------------------------------------------------------------------------

def _enabled_zone(crop_x=0, crop_y=0, crop_w=1920, crop_h=1080,
                  scale_w=-1, scale_h=-1, border_px=0, offset_y=0):
    return {
        "enabled": True,
        "crop_x": crop_x, "crop_y": crop_y,
        "crop_w": crop_w, "crop_h": crop_h,
        "scale_w": scale_w, "scale_h": scale_h,
        "border_px": border_px,
        "offset_y": offset_y,
        "mode": "crop",
    }


def _make_cfg(*zones, direction="horizontal", **extra):
    all_zones = list(zones)
    while len(all_zones) < NUM_ZONES:
        all_zones.append(_default_zone())
    d = {"zones": all_zones, "stack_direction": direction, "frame_snapshot_path": ""}
    d.update(extra)
    return d


def test_empty_config_returns_none():
    assert _build_vf_for_zones({}) is None


def test_no_enabled_zones_returns_none():
    cfg = _make_cfg(*[_default_zone() for _ in range(NUM_ZONES)])
    assert _build_vf_for_zones(cfg) is None


def test_single_zone_simple_crop():
    cfg = _make_cfg(_enabled_zone(crop_x=0, crop_y=0, crop_w=960, crop_h=540))
    result = _build_vf_for_zones(cfg)
    assert result == "lavfi=[crop=960:540:0:0,setsar=1]"


def test_single_zone_with_scale():
    cfg = _make_cfg(_enabled_zone(crop_w=1920, crop_h=1080,
                                   scale_w=1280, scale_h=720))
    result = _build_vf_for_zones(cfg)
    assert result == "lavfi=[crop=1920:1080:0:0,scale=1280:720,setsar=1]"


def test_single_zone_with_border():
    cfg = _make_cfg(_enabled_zone(crop_w=1920, crop_h=1080, border_px=10))
    result = _build_vf_for_zones(cfg)
    assert "pad=iw+20:ih+20:10:10:black" in result


def test_single_zone_positive_offset_y():
    cfg = _make_cfg(_enabled_zone(crop_w=1920, crop_h=1080, offset_y=50))
    result = _build_vf_for_zones(cfg)
    assert "pad=iw:ih+50:0:50:black,crop=iw:ih:0:0" in result


def test_single_zone_negative_offset_y():
    cfg = _make_cfg(_enabled_zone(crop_w=1920, crop_h=1080, offset_y=-50))
    result = _build_vf_for_zones(cfg)
    assert "pad=iw:ih+50:0:0:black,crop=iw:ih:0:50" in result


def test_two_zones_horizontal_stitch():
    z0 = _enabled_zone(crop_w=960, crop_h=540)
    z1 = _enabled_zone(crop_x=960, crop_w=960, crop_h=540)
    cfg = _make_cfg(z0, z1, direction="horizontal")
    result = _build_vf_for_zones(cfg)
    assert "hstack=inputs=2" in result
    assert "split=2" in result
    assert result.startswith("lavfi=[")


def test_two_zones_vertical_stitch():
    z0 = _enabled_zone(crop_w=1920, crop_h=540)
    z1 = _enabled_zone(crop_y=540, crop_w=1920, crop_h=540)
    cfg = _make_cfg(z0, z1, direction="vertical")
    result = _build_vf_for_zones(cfg)
    assert "vstack=inputs=2" in result


def test_multi_zone_different_heights_padded():
    """Zones with different heights are padded to match the tallest."""
    z0 = _enabled_zone(crop_w=960, crop_h=1080)
    z1 = _enabled_zone(crop_w=960, crop_h=540)
    cfg = _make_cfg(z0, z1, direction="horizontal")
    result = _build_vf_for_zones(cfg)
    # z1 is shorter — it should get a height-padding filter
    assert "pad=iw:1080:0:0:black" in result


def test_single_zone_no_composite_transform_legacy():
    """Legacy config: no composite/output fields → no extra filters in graph."""
    cfg = _make_cfg(_enabled_zone(crop_w=1920, crop_h=1080))
    # out_w is absent — backfilled as -1 by migration
    result = _build_vf_for_zones(cfg)
    # Must not contain composite crop/scale/pad
    assert "comp" not in result
    assert result == "lavfi=[crop=1920:1080:0:0,setsar=1]"


def test_composite_crop_applied_single_zone():
    cfg = _make_cfg(
        _enabled_zone(crop_w=1920, crop_h=1080),
        comp_crop_x=10, comp_crop_y=5, comp_crop_w=1900, comp_crop_h=1070,
    )
    result = _build_vf_for_zones(cfg)
    assert "crop=1900:1070:10:5" in result


def test_composite_scale_applied_single_zone():
    cfg = _make_cfg(
        _enabled_zone(crop_w=1920, crop_h=1080),
        comp_scale_w=1280, comp_scale_h=720,
    )
    result = _build_vf_for_zones(cfg)
    assert "scale=1280:720" in result


def test_output_canvas_pad_when_sim_enabled():
    cfg = _make_cfg(
        _enabled_zone(crop_w=1280, crop_h=720),
        out_w=1920, out_h=1080, out_sim_enabled=True,
    )
    result = _build_vf_for_zones(cfg)
    assert "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black" in result


def test_output_canvas_NOT_applied_when_sim_disabled():
    cfg = _make_cfg(
        _enabled_zone(crop_w=1280, crop_h=720),
        out_w=1920, out_h=1080, out_sim_enabled=False,
    )
    result = _build_vf_for_zones(cfg)
    assert "pad=1920" not in result


def test_output_canvas_NOT_applied_when_out_w_minus1():
    """Existing (migrated) configs with out_w=-1 must not get padding."""
    cfg = _make_cfg(
        _enabled_zone(crop_w=1280, crop_h=720),
        out_w=-1, out_h=-1, out_sim_enabled=True,   # sim=True but out_w=-1
    )
    result = _build_vf_for_zones(cfg)
    assert "pad=" not in result


def test_composite_crop_zero_width_is_noop():
    """comp_crop_w=0 must not produce a crop filter."""
    cfg = _make_cfg(
        _enabled_zone(crop_w=1920, crop_h=1080),
        comp_crop_w=0, comp_crop_h=0,
    )
    result = _build_vf_for_zones(cfg)
    assert result == "lavfi=[crop=1920:1080:0:0,setsar=1]"


def test_composite_scale_minus1_is_noop():
    """comp_scale_w=-1 must not produce a scale filter."""
    cfg = _make_cfg(
        _enabled_zone(crop_w=1920, crop_h=1080),
        comp_scale_w=-1, comp_scale_h=-1,
    )
    result = _build_vf_for_zones(cfg)
    assert "scale=" not in result


def test_full_pipeline_single_zone():
    """Verify full pipeline order: zone crop → comp crop → comp scale → pad → setsar=1."""
    cfg = _make_cfg(
        _enabled_zone(crop_x=100, crop_y=50, crop_w=1720, crop_h=980),
        comp_crop_x=0, comp_crop_y=0, comp_crop_w=1600, comp_crop_h=900,
        comp_scale_w=1280, comp_scale_h=720,
        out_w=1920, out_h=1080, out_sim_enabled=True,
    )
    result = _build_vf_for_zones(cfg)
    # Check correct order
    zone_pos  = result.index("crop=1720:980:100:50")
    ccrop_pos = result.index("crop=1600:900:0:0")
    scale_pos = result.index("scale=1280:720")
    pad_pos   = result.index("pad=1920:1080")
    setsar_pos = result.index("setsar=1")
    assert zone_pos < ccrop_pos < scale_pos < pad_pos < setsar_pos


def test_setsar_always_present():
    cfg = _make_cfg(_enabled_zone(crop_w=1920, crop_h=1080))
    result = _build_vf_for_zones(cfg)
    assert "setsar=1" in result


def test_old_single_zone_format_enabled():
    """Old single-zone dict (not multi-zone) is correctly handled."""
    old = {"enabled": True, "crop_x": 0, "crop_y": 0,
           "crop_w": 1920, "crop_h": 1080, "scale_w": -1, "scale_h": -1}
    result = _build_vf_for_zones(old)
    assert result is not None
    assert "crop=1920:1080:0:0" in result


def test_old_single_zone_format_disabled_returns_none():
    old = {"enabled": False, "crop_x": 0, "crop_y": 0,
           "crop_w": 1920, "crop_h": 1080}
    assert _build_vf_for_zones(old) is None


def test_make_unique_mpv_pipe_name_uses_prefix():
    pipe_path = _make_unique_mpv_pipe_name("mpv_test")
    assert pipe_path.startswith(r"\\.\pipe\mpv_test_")


def test_make_unique_mpv_pipe_name_is_unique():
    a = _make_unique_mpv_pipe_name("mpv_test")
    b = _make_unique_mpv_pipe_name("mpv_test")
    assert a != b


def test_send_mpv_ipc_command_missing_path_returns_error():
    ok, err = _send_mpv_ipc_command("", ["quit"])
    assert ok is False
    assert "Missing IPC pipe path" in err


def test_send_mpv_ipc_command_retries_requested_attempts(monkeypatch):
    calls = {"count": 0}

    def _always_fail(*_args, **_kwargs):
        calls["count"] += 1
        raise OSError("pipe unavailable")

    monkeypatch.setattr("builtins.open", _always_fail)
    ok, err = _send_mpv_ipc_command(r"\\.\pipe\missing_pipe", ["quit"], max_attempts=3, retry_delay=0)
    assert ok is False
    assert "pipe unavailable" in err
    assert calls["count"] == 3


# ---------------------------------------------------------------------------
# _ext_preview_vf_command tests
# ---------------------------------------------------------------------------

def test_ext_preview_vf_command_non_empty():
    """Non-empty vf string → vf set command."""
    cmd = _ext_preview_vf_command("lavfi=[crop=100:100:0:0,setsar=1]")
    assert cmd == ["vf", "set", "lavfi=[crop=100:100:0:0,setsar=1]"]


def test_ext_preview_vf_command_empty_string():
    """Empty vf string → vf clr command (clears the filter chain)."""
    cmd = _ext_preview_vf_command("")
    assert cmd == ["vf", "clr", ""]


def test_ext_preview_vf_command_none_via_build():
    """_build_vf_for_zones returns None for no-filter; caller normalises with ``or ""``,
    and _ext_preview_vf_command must then produce a clr command."""
    vf_str = _build_vf_for_zones({}) or ""
    assert vf_str == ""
    cmd = _ext_preview_vf_command(vf_str)
    assert cmd == ["vf", "clr", ""]


def test_ext_preview_vf_command_real_single_zone():
    """A real single-zone filter string is passed through to a set command."""
    cfg = _make_cfg(_enabled_zone(crop_x=0, crop_y=0, crop_w=1920, crop_h=1080))
    vf_str = _build_vf_for_zones(cfg)
    assert vf_str  # must be non-empty
    cmd = _ext_preview_vf_command(vf_str)
    assert cmd[0] == "vf"
    assert cmd[1] == "set"
    assert cmd[2] == vf_str
