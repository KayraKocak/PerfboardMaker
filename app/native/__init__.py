"""
Native C++ router loader and ctypes bridge for PerfBoardMaker.
Falls back gracefully if router_core.dll cannot be loaded.
"""
import ctypes
from ctypes import c_int32, c_int64, POINTER
import os
from typing import Any


def _load_native_lib():
    dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "router_core.dll")
    if not os.path.isfile(dll_path):
        return None
    try:
        lib = ctypes.CDLL(dll_path)
        lib.rc_free_buffer.argtypes = [POINTER(c_int32)]
        lib.rc_free_buffer.restype = None
        lib.rc_solve_multi.argtypes = [
            c_int32, c_int32,
            POINTER(c_int64),
            POINTER(c_int32), c_int32,
            POINTER(c_int32), c_int32,
            POINTER(c_int32), c_int32,
            POINTER(c_int32), c_int32,
            POINTER(c_int32),
        ]
        lib.rc_solve_multi.restype = POINTER(c_int32)
        return lib
    except OSError:
        return None


_NATIVE_LIB = _load_native_lib()


def is_native_available() -> bool:
    return _NATIVE_LIB is not None


def _pack_i32_arr(vals: list[int]):
    if not vals:
        return POINTER(c_int32)(), 0
    arr = (c_int32 * len(vals))(*vals)
    return arr, len(vals)


def _unpack_i64(lo: int, hi: int) -> int:
    u = (lo & 0xFFFFFFFF) | ((hi & 0xFFFFFFFF) << 32)
    return u - (1 << 64) if (u & (1 << 63)) else u


def solve_groups_native(
    cols: int,
    rows: int,
    settings: Any,
    base_obstacles: set[tuple[int, int]],
    all_pin_holes: set[tuple[int, int]],
    existing_jumpers: list[Any],
    groups: list[Any],
) -> dict[str, Any] | None:
    """
    Solves single or multiple AutoConnect groups using compiled native C++ router_core.dll.
    Returns parsed solution dict or None if native library is unavailable.
    """
    lib = _NATIVE_LIB
    if lib is None:
        return None

    settings_arr = (c_int64 * 6)(
        int(settings.cost_solder_move),
        int(settings.cost_solder_turn),
        int(settings.cost_jumper_start),
        int(settings.cost_jumper_move),
        int(settings.cost_jumper_turn),
        int(settings.cost_jumper_cross),
    )

    obs_flat = [r * cols + c for c, r in base_obstacles if 0 <= c < cols and 0 <= r < rows]
    pins_flat = [r * cols + c for c, r in all_pin_holes if 0 <= c < cols and 0 <= r < rows]
    obs_ptr, n_obs = _pack_i32_arr(obs_flat)
    pins_ptr, n_pins = _pack_i32_arr(pins_flat)

    j_flat: list[int] = []
    for j in existing_jumpers:
        if isinstance(j, dict):
            sx, sy = j["start"]
            ex, ey = j["end"]
            bends = j.get("bends", [])
        else:
            sx, sy = j.start_col, j.start_row
            ex, ey = j.end_col, j.end_row
            bends = getattr(j, "bends", [])
        j_flat.extend((int(sx), int(sy), int(ex), int(ey), len(bends)))
        for bx, by in bends:
            j_flat.extend((int(bx), int(by)))
    j_ptr, _ = _pack_i32_arr(j_flat)
    n_existing_j = len(existing_jumpers)

    g_flat: list[int] = []
    group_color_map: dict[int, str] = {}
    for g in groups:
        group_color_map[g.id] = g.color
        g_flat.append(int(g.id))
        g_flat.append(len(g.targets))
        for t in g.targets:
            valid_holes = [r * cols + c for c, r in t.holes if 0 <= c < cols and 0 <= r < rows]
            g_flat.append(len(valid_holes))
            g_flat.extend(valid_holes)
    g_ptr, _ = _pack_i32_arr(g_flat)

    out_len = c_int32(0)
    res_ptr = lib.rc_solve_multi(
        c_int32(cols), c_int32(rows),
        settings_arr,
        obs_ptr, c_int32(n_obs),
        pins_ptr, c_int32(n_pins),
        j_ptr, c_int32(n_existing_j),
        g_ptr, c_int32(len(groups)),
        ctypes.byref(out_len),
    )

    try:
        if not res_ptr or out_len.value <= 0:
            return {"success": False, "solder_segments": [], "jumpers": [], "total_cost": 0, "group_details": []}

        pos = 0
        success = bool(res_ptr[pos]); pos += 1
        total_cost = _unpack_i64(res_ptr[pos], res_ptr[pos + 1]); pos += 2
        n_res_groups = res_ptr[pos]; pos += 1

        if not success:
            return {
                "success": False,
                "solder_segments": [],
                "jumpers": [],
                "total_cost": 0,
                "group_details": [],
            }

        all_solders: list[tuple[tuple[int, int], tuple[int, int]]] = []
        all_jumpers: list[dict[str, Any]] = []
        group_details: list[dict[str, Any]] = []

        for _ in range(n_res_groups):
            gid = int(res_ptr[pos]); pos += 1
            g_cost = _unpack_i64(res_ptr[pos], res_ptr[pos + 1]); pos += 2
            g_color = group_color_map.get(gid, "#00e6ff")

            n_solders = int(res_ptr[pos]); pos += 1
            g_solders: list[tuple[tuple[int, int], tuple[int, int]]] = []
            for _ in range(n_solders):
                h1 = int(res_ptr[pos]); h2 = int(res_ptr[pos + 1]); pos += 2
                seg = ((h1 % cols, h1 // cols), (h2 % cols, h2 // cols))
                g_solders.append(seg)

            n_jumpers = int(res_ptr[pos]); pos += 1
            g_jumpers: list[dict[str, Any]] = []
            for _ in range(n_jumpers):
                sx = int(res_ptr[pos]); sy = int(res_ptr[pos + 1])
                ex = int(res_ptr[pos + 2]); ey = int(res_ptr[pos + 3])
                nb = int(res_ptr[pos + 4]); pos += 5
                bends: list[tuple[int, int]] = []
                for _ in range(nb):
                    bx = int(res_ptr[pos]); by = int(res_ptr[pos + 1]); pos += 2
                    bends.append((bx, by))
                j_dict = {
                    "start": (sx, sy),
                    "end": (ex, ey),
                    "bends": bends,
                    "side": "top",
                    "color": g_color,
                }
                g_jumpers.append(j_dict)

            all_solders.extend(g_solders)
            all_jumpers.extend(g_jumpers)
            group_details.append({
                "group_id": gid,
                "color": g_color,
                "cost": g_cost,
                "solders": g_solders,
                "jumpers": g_jumpers,
            })

        return {
            "success": True,
            "solder_segments": all_solders,
            "jumpers": all_jumpers,
            "total_cost": total_cost,
            "group_details": group_details,
        }
    finally:
        if res_ptr:
            lib.rc_free_buffer(res_ptr)
