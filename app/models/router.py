"""
AutoConnect routing engine for PerfBoardMaker.
Finds optimal connections between selected pins, solder traces, and jumper ends.
Balances solder bridging costs against jumper wire placement and bends.
"""
from collections import defaultdict, deque
import itertools
import colorsys
from dataclasses import dataclass, field
import heapq
import math
from typing import Any, Optional
from app.models.board import BoardConfig
from app.models.solder import SolderManager, SolderTrace
from app.models.jumper import JumperWire
from app.models.placed_component import PlacedComponent
try:
    from app.native import solve_groups_native, is_native_available
except Exception:
    def is_native_available() -> bool:
        return False
    def solve_groups_native(*args, **kwargs):
        return None

@dataclass
class AutoConnectSettings:
    """Cost weights for auto-routing connections on the perfboard."""
    cost_solder_move: int = 10   # Moving one hole over with solder
    cost_solder_turn: int = 15   # Changing direction with solder is annoying
    cost_jumper_start: int = 50  # Stripping wire & soldering two points
    cost_jumper_move: int = 2    # Extending jumper wire per hole
    cost_jumper_turn: int = 30   # Bending a jumper wire 90 degrees
    cost_jumper_cross: int = 100 # Jumpers crossing each other

    def copy(self) -> "AutoConnectSettings":
        return AutoConnectSettings(
            cost_solder_move=self.cost_solder_move,
            cost_solder_turn=self.cost_solder_turn,
            cost_jumper_start=self.cost_jumper_start,
            cost_jumper_move=self.cost_jumper_move,
            cost_jumper_turn=self.cost_jumper_turn,
            cost_jumper_cross=self.cost_jumper_cross,
        )


@dataclass(eq=False)
class AutoConnectTarget:
    """A user-selected conductor target (pin, solder trace, or jumper end)."""
    target_type: str  # "pin", "solder", "jumper_end"
    label: str
    holes: set[tuple[int, int]] = field(default_factory=set)
    center_hole: tuple[int, int] = (0, 0)
    # References for tracking
    component_item: Any = None
    pin_name: str = ""
    solder_trace: Optional[SolderTrace] = None
    jumper_item: Any = None
    jumper_end_idx: int = 0  # 0 for start, 1 for end

    def __hash__(self):
        return hash((self.target_type, self.center_hole, self.label))

    def __eq__(self, other):
        if not isinstance(other, AutoConnectTarget):
            return False
        return (self.target_type == other.target_type and
                self.center_hole == other.center_hole and
                self.label == other.label)


GROUP_COLORS = [
    "#FF5722",  # Deep Orange
    "#00E676",  # Bright Green
    "#E91E63",  # Vibrant Pink
    "#FFD600",  # Vivid Yellow
    "#9C27B0",  # Purple
    "#00B0FF",  # Light Blue
    "#FF9100",  # Amber
    "#00E5FF",  # Cyan
    "#D500F9",  # Magenta
    "#76FF03",  # Lime
    "#FF1744",  # Bright Red
    "#1DE9B6",  # Teal
]


def get_group_color(index: int) -> str:
    """Returns a bright, distinguishable hex color for a conductor group."""
    if 0 <= index < len(GROUP_COLORS):
        return GROUP_COLORS[index]
    h = (index * 0.618033988749895) % 1.0  # Golden ratio hue spacing
    r, g, b = colorsys.hsv_to_rgb(h, 0.85, 0.95)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


@dataclass
class AutoConnectGroup:
    """A user-defined group of conductors to be routed together as a distinct electrical net."""
    id: int
    color: str
    targets: list[AutoConnectTarget] = field(default_factory=list)

    def all_holes(self) -> set[tuple[int, int]]:
        holes: set[tuple[int, int]] = set()
        for t in self.targets:
            holes.update(t.holes)
        return holes

    def copy(self) -> "AutoConnectGroup":
        return AutoConnectGroup(
            id=self.id,
            color=self.color,
            targets=list(self.targets)
        )


def get_all_obstacle_holes(
    config: BoardConfig,
    solder_mgr: SolderManager,
    jumpers: list[JumperWire],
    components: list[PlacedComponent],
    registry: Any,
    allowed_holes: set[tuple[int, int]]
) -> set[tuple[int, int]]:
    """
    Returns all holes that belong to other conductive paths (unselected pins,
    solder traces, or jumper endpoints), excluding the allowed target holes.
    """
    obstacles: set[tuple[int, int]] = set()

    # 1. Component pins
    for comp in components:
        comp_def = registry.get(comp.type_id)
        if comp_def:
            for _, c, r, _ in comp.get_pin_positions(comp_def):
                if config.is_valid_hole(c, r) and (c, r) not in allowed_holes:
                    obstacles.add((c, r))

    # 2. Solder traces
    for trace in solder_mgr.traces:
        for h in trace.holes:
            if h not in allowed_holes:
                obstacles.add(h)

    # 3. Jumper endpoints
    for j in jumpers:
        for end in ((j.start_col, j.start_row), (j.end_col, j.end_row)):
            if end not in allowed_holes:
                obstacles.add(end)

    return obstacles


def route_solder_path(
    start_holes: set[tuple[int, int]],
    goal_holes: set[tuple[int, int]],
    obstacle_holes: set[tuple[int, int]],
    config: BoardConfig,
    settings: AutoConnectSettings
) -> tuple[int, list[tuple[int, int]]]:
    """
    Finds the lowest-cost solder path on the grid connecting start_holes to goal_holes
    avoiding obstacle_holes using A* search.
    Returns (cost, list_of_holes). If unreachable, returns (math.inf, []).
    """
    if not start_holes or not goal_holes:
        return (math.inf, [])

    # Check for direct overlap
    common = start_holes.intersection(goal_holes)
    if common:
        h = next(iter(common))
        return (0, [h])

    # Directions: 0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)
    DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]

    def heuristic(c: int, r: int) -> int:
        return min(abs(c - gc) + abs(r - gr) for gc, gr in goal_holes) * settings.cost_solder_move

    # Priority Queue: (f_score, g_cost, col, row, dir_idx)
    pq = []
    # min_cost table: (col, row, dir_idx) -> g_cost
    g_costs: dict[tuple[int, int, int], int] = {}
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}

    for sc, sr in start_holes:
        state = (sc, sr, -1)
        g_costs[state] = 0
        h = heuristic(sc, sr)
        heapq.heappush(pq, (h, 0, sc, sr, -1))

    best_goal_state: tuple[int, int, int] | None = None
    best_goal_cost = math.inf

    while pq:
        f, g, c, r, d_idx = heapq.heappop(pq)
        curr_state = (c, r, d_idx)

        if g > g_costs.get(curr_state, math.inf):
            continue

        if (c, r) in goal_holes:
            best_goal_state = curr_state
            best_goal_cost = g
            break

        for new_d_idx, (dc, dr) in enumerate(DIRS):
            nc, nr = c + dc, r + dr

            if not config.is_valid_hole(nc, nr):
                continue
            if (nc, nr) in obstacle_holes:
                continue

            # Calculate turn cost
            turn_cost = 0
            if d_idx != -1 and new_d_idx != d_idx:
                turn_cost = settings.cost_solder_turn

            move_cost = settings.cost_solder_move + turn_cost
            new_g = g + move_cost
            next_state = (nc, nr, new_d_idx)

            if new_g < g_costs.get(next_state, math.inf):
                g_costs[next_state] = new_g
                came_from[next_state] = curr_state
                new_f = new_g + heuristic(nc, nr)
                heapq.heappush(pq, (new_f, new_g, nc, nr, new_d_idx))

    if best_goal_state is None:
        return (math.inf, [])

    # Reconstruct path
    path = []
    curr = best_goal_state
    while curr in came_from:
        path.append((curr[0], curr[1]))
        curr = came_from[curr]
    path.append((curr[0], curr[1]))
    path.reverse()

    return (best_goal_cost, path)


def ccw(A: tuple[float, float], B: tuple[float, float], C: tuple[float, float]) -> float:
    return (C[1] - A[1]) * (B[0] - A[0]) - (B[1] - A[1]) * (C[0] - A[0])


def segments_cross(
    p1: tuple[int, int], p2: tuple[int, int],
    p3: tuple[int, int], p4: tuple[int, int]
) -> bool:
    """Returns True if open segments (p1, p2) and (p3, p4) intersect/cross."""
    if p1 in (p3, p4) or p2 in (p3, p4):
        return False

    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    # Collinear overlap check
    if d1 == 0 and d2 == 0 and d3 == 0 and d4 == 0:
        min_x12, max_x12 = min(p1[0], p2[0]), max(p1[0], p2[0])
        min_y12, max_y12 = min(p1[1], p2[1]), max(p1[1], p2[1])
        min_x34, max_x34 = min(p3[0], p4[0]), max(p3[0], p4[0])
        min_y34, max_y34 = min(p3[1], p4[1]), max(p3[1], p4[1])

        overlap_x = max(min_x12, min_x34) < min(max_x12, max_x34)
        overlap_y = max(min_y12, min_y34) < min(max_y12, max_y34)

        if p1[0] == p2[0]:
            return overlap_y
        if p1[1] == p2[1]:
            return overlap_x
        return overlap_x and overlap_y

    return False


def pt_strictly_on_open_segment(pt: tuple[int, int], p1: tuple[int, int], p2: tuple[int, int]) -> bool:
    """Returns True if pt lies strictly inside the open line segment between p1 and p2 (excluding endpoints)."""
    if pt == p1 or pt == p2:
        return False
    # Collinear check: cross product == 0
    if (pt[1] - p1[1]) * (p2[0] - p1[0]) != (p2[1] - p1[1]) * (pt[0] - p1[0]):
        return False
    # In bounding box
    min_x, max_x = min(p1[0], p2[0]), max(p1[0], p2[0])
    min_y, max_y = min(p1[1], p2[1]), max(p1[1], p2[1])
    return min_x <= pt[0] <= max_x and min_y <= pt[1] <= max_y


def count_jumper_crossings(
    j_start: tuple[int, int],
    j_end: tuple[int, int],
    j_bends: list[tuple[int, int]],
    existing_jumpers: list[Any],
    cost_jumper_cross: int = 100
) -> int:
    """
    Computes total crossing penalty according to exact rules:
    1. When 2 jumpers cross, add the cross cost for every cross point.
    2. When 2 parallel lines run along the same path, every point they are running on top of each other, add the cross cost.
    3. For one end of a jumper crossing a body of another jumper, add half the cross cost.
    Returns the total crossing cost (as an integer).
    """
    cand_pts = [j_start] + list(j_bends) + [j_end]
    cand_segs = [(cand_pts[i], cand_pts[i + 1]) for i in range(len(cand_pts) - 1)]
    cand_endpoints = {j_start, j_end}

    total_cost = 0.0

    for other in existing_jumpers:
        if isinstance(other, dict):
            o_start = other["start"]
            o_end = other["end"]
            o_bends = other.get("bends", [])
        else:
            o_start = (other.start_col, other.start_row)
            o_end = (other.end_col, other.end_row)
            o_bends = getattr(other, "bends", [])

        o_pts = [o_start] + list(o_bends) + [o_end]
        o_segs = [(o_pts[i], o_pts[i + 1]) for i in range(len(o_pts) - 1)]
        o_endpoints = {o_start, o_end}

        # Rule 3: For one end of a jumper crossing a body of another jumper, add half the cross cost.
        def is_collinear_seg(sa: tuple[tuple[int, int], tuple[int, int]], sb: tuple[tuple[int, int], tuple[int, int]]) -> bool:
            dxa, dya = sa[1][0] - sa[0][0], sa[1][1] - sa[0][1]
            dxb, dyb = sb[1][0] - sb[0][0], sb[1][1] - sb[0][1]
            return dxa * dyb == dya * dxb

        for ep in cand_endpoints:
            for s in o_segs:
                if pt_strictly_on_open_segment(ep, s[0], s[1]):
                    # Do not double-count if this endpoint is part of a parallel overlap segment
                    connected = [cs for cs in cand_segs if ep in cs]
                    if not any(is_collinear_seg(cs, s) for cs in connected):
                        total_cost += 0.5 * cost_jumper_cross

        for ep in o_endpoints:
            for s in cand_segs:
                if pt_strictly_on_open_segment(ep, s[0], s[1]):
                    connected = [os for os in o_segs if ep in os]
                    if not any(is_collinear_seg(os, s) for os in connected):
                        total_cost += 0.5 * cost_jumper_cross

        # Rules 1 & 2: Segment-by-segment crossings and parallel overlaps
        for s1 in cand_segs:
            p1, p2 = s1
            for s2 in o_segs:
                p3, p4 = s2

                # Rule 2: Parallel lines running along the same path
                # Horizontal parallel overlap
                if p1[1] == p2[1] == p3[1] == p4[1]:
                    min1, max1 = min(p1[0], p2[0]), max(p1[0], p2[0])
                    min2, max2 = min(p3[0], p4[0]), max(p3[0], p4[0])
                    ov_min = max(min1, min2)
                    ov_max = min(max1, max2)
                    if ov_min < ov_max:
                        # Add cross cost for every point running on top of each other
                        for _ in range(ov_min, ov_max + 1):
                            total_cost += cost_jumper_cross
                    continue

                # Vertical parallel overlap
                if p1[0] == p2[0] == p3[0] == p4[0]:
                    min1, max1 = min(p1[1], p2[1]), max(p1[1], p2[1])
                    min2, max2 = min(p3[1], p4[1]), max(p3[1], p4[1])
                    ov_min = max(min1, min2)
                    ov_max = min(max1, max2)
                    if ov_min < ov_max:
                        for _ in range(ov_min, ov_max + 1):
                            total_cost += cost_jumper_cross
                    continue

                # Diagonal parallel overlap
                dx1, dy1 = p2[0] - p1[0], p2[1] - p1[1]
                dx2, dy2 = p4[0] - p3[0], p4[1] - p3[1]
                if dx1 * dy2 == dy1 * dx2: # Same slope
                    # Collinear check with p3
                    if (p3[1] - p1[1]) * dx1 == (p3[0] - p1[0]) * dy1:
                        min1_x, max1_x = min(p1[0], p2[0]), max(p1[0], p2[0])
                        min2_x, max2_x = min(p3[0], p4[0]), max(p3[0], p4[0])
                        ov_min_x = max(min1_x, min2_x)
                        ov_max_x = min(max1_x, max2_x)
                        if ov_min_x < ov_max_x:
                            for _ in range(ov_min_x, ov_max_x + 1):
                                total_cost += cost_jumper_cross
                        continue

                # Rule 1: Every cross point
                d1 = ccw(p3, p4, p1)
                d2 = ccw(p3, p4, p2)
                d3 = ccw(p1, p2, p3)
                d4 = ccw(p1, p2, p4)

                if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
                   ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
                    total_cost += cost_jumper_cross

    return int(total_cost)


def get_jumper_terminals_for_group(
    group: set[tuple[int, int]],
    all_pin_holes: set[tuple[int, int]],
    obstacle_holes: set[tuple[int, int]],
    config: BoardConfig,
    settings: AutoConnectSettings,
    max_solder_depth: int = 6
) -> list[tuple[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int]]], int]]:
    """
    Returns candidate holes where a jumper can attach to connect with this group:
    (terminal_hole, extra_solder_segments, extra_solder_cost)
    Full-hybrid capability:
    - Zero-solder terminals: holes already in group that have no pin and are not obstacles.
    - Solder-extension terminals: holes reachable via valid solder paths extending up to
      max_solder_depth steps on vacant perfboard holes (avoiding obstacle_holes and other
      components' pins).
    - Enables optimal combinations: Solder -> Jumper -> Solder, Jumper -> Solder, Solder -> Jumper,
      or pure Jumper, picking whichever minimizes total electrical and physical connection cost.
    """
    terminals: list[tuple[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int]]], int]] = []
    seen_terminal_holes: set[tuple[int, int]] = set()
    best_terminal_segs: dict[tuple[int, int], tuple[list[tuple[tuple[int, int], tuple[int, int]]], int]] = {}

    # 1. Zero-solder terminals: holes already in group that have no pin and are not obstacles
    for h in group:
        if h not in all_pin_holes and h not in obstacle_holes:
            if h not in seen_terminal_holes:
                seen_terminal_holes.add(h)
                terminals.append((h, [], 0))

    # 2. Dijkstra multi-step solder expansion to find hybrid terminal launch/landing points
    DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    pq: list[tuple[int, int, int, int, int]] = []  # (g_cost, steps, col, row, dir_idx)
    g_costs: dict[tuple[int, int, int], int] = {}
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}

    for sc, sr in group:
        if (sc, sr) not in obstacle_holes:
            state = (sc, sr, -1)
            g_costs[state] = 0
            heapq.heappush(pq, (0, 0, sc, sr, -1))

    while pq:
        g, steps, c, r, d = heapq.heappop(pq)
        curr = (c, r, d)

        if g > g_costs.get(curr, math.inf):
            continue
        if steps >= max_solder_depth:
            continue

        for new_d, (dc, dr) in enumerate(DIRS):
            nc, nr = c + dc, r + dr
            if not config.is_valid_hole(nc, nr):
                continue
            if (nc, nr) in obstacle_holes:
                continue
            # Cannot solder through pins of another component
            if (nc, nr) in all_pin_holes and (nc, nr) not in group:
                continue

            turn_cost = settings.cost_solder_turn if (d != -1 and new_d != d) else 0
            new_g = g + settings.cost_solder_move + turn_cost
            nxt = (nc, nr, new_d)

            if new_g < g_costs.get(nxt, math.inf):
                g_costs[nxt] = new_g
                came_from[nxt] = curr
                heapq.heappush(pq, (new_g, steps + 1, nc, nr, new_d))

                # Jumpers cannot start on a component pin; only vacant holes are valid jumper terminals
                if (nc, nr) not in all_pin_holes:
                    if (nc, nr) not in best_terminal_segs or new_g < best_terminal_segs[(nc, nr)][1]:
                        # Reconstruct solder path segments
                        path = []
                        track = nxt
                        while track in came_from:
                            path.append((track[0], track[1]))
                            track = came_from[track]
                        path.append((track[0], track[1]))
                        path.reverse()
                        segs = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
                        best_terminal_segs[(nc, nr)] = (segs, new_g)

    # Add all unique hybrid terminals
    for hole, (segs, cost) in best_terminal_segs.items():
        if hole not in seen_terminal_holes:
            seen_terminal_holes.add(hole)
            terminals.append((hole, segs, cost))

    return terminals


def point_to_segment_dist(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculates perpendicular or endpoint distance from point (px, py) to segment (x1, y1)-(x2, y2)."""
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def is_straight_segment_clear_of_pins(
    p1: tuple[int, int],
    p2: tuple[int, int],
    all_pin_holes: set[tuple[int, int]],
    is_terminal: bool = True
) -> bool:
    """
    Checks if a straight jumper segment between p1 and p2 touches or passes over any component pin,
    or runs between 2 neighboring pins.
    - Orthogonal segment: checks if any grid hole along the segment is in all_pin_holes.
    - Diagonal segment: checks that distance from any pin in all_pin_holes is >= 0.85 grid units,
      which strictly prevents running between adjacent pins (0.5 away) or diagonal pins (0.707 away).
    """
    if p1 == p2:
        return p1 not in all_pin_holes

    # Orthogonal horizontal segment
    if p1[1] == p2[1]:
        r = p1[1]
        min_c = min(p1[0], p2[0])
        max_c = max(p1[0], p2[0])
        for c in range(min_c, max_c + 1):
            if (c, r) in all_pin_holes:
                return False
        return True

    # Orthogonal vertical segment
    if p1[0] == p2[0]:
        c = p1[0]
        min_r = min(p1[1], p2[1])
        max_r = max(p1[1], p2[1])
        for r in range(min_r, max_r + 1):
            if (c, r) in all_pin_holes:
                return False
        return True

    # Diagonal segment
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    min_x, max_x = min(x1, x2) - 1.0, max(x1, x2) + 1.0
    min_y, max_y = min(y1, y2) - 1.0, max(y1, y2) + 1.0

    for pc, pr in all_pin_holes:
        px, py = float(pc), float(pr)
        # Fast bounding box check
        if min_x <= px <= max_x and min_y <= py <= max_y:
            # Clearance must be at least 0.85 grid units:
            # Adjacent pins: distance is <= 0.5 (< 0.85) -> REJECTED
            # Diagonal pins: distance is 0.707 (< 0.85) -> REJECTED
            # Adjacent vacant row/col: distance is 1.0 (>= 0.85) -> ALLOWED
            if point_to_segment_dist(px, py, x1, y1, x2, y2) < 0.85:
                return False

    return True


def find_orthogonal_jumper_path(
    start: tuple[int, int],
    goal: tuple[int, int],
    all_pin_holes: set[tuple[int, int]],
    obstacle_holes: set[tuple[int, int]],
    config: BoardConfig,
    settings: AutoConnectSettings
) -> tuple[int, list[tuple[int, int]]]:
    """
    A* grid pathfinder that routes an orthogonal jumper wire with 90° bends around
    all component pins (all_pin_holes) from start to goal.
    Returns (path_cost, list_of_bends). If no path exists, returns (math.inf, []).
    """
    DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    pq = []
    g_costs: dict[tuple[int, int, int], int] = {}
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}

    h_start = (abs(goal[0] - start[0]) + abs(goal[1] - start[1])) * settings.cost_jumper_move
    for d_idx in range(4):
        state = (start[0], start[1], d_idx)
        g_costs[state] = 0
        heapq.heappush(pq, (h_start, 0, start[0], start[1], d_idx))

    best_goal_state = None
    best_cost = math.inf

    while pq:
        f, g, c, r, d = heapq.heappop(pq)
        curr = (c, r, d)

        if g > g_costs.get(curr, math.inf):
            continue

        if (c, r) == goal:
            best_goal_state = curr
            best_cost = g
            break

        for new_d, (dc, dr) in enumerate(DIRS):
            # No 180° turns
            if (new_d + 2) % 4 == d:
                continue

            nc, nr = c + dc, r + dr
            if not config.is_valid_hole(nc, nr):
                continue
            if (nc, nr) in all_pin_holes:
                continue

            turn_cost = settings.cost_jumper_turn if new_d != d else 0
            bend_penalty = 500 if (new_d != d and (c, r) in obstacle_holes) else 0
            new_g = g + settings.cost_jumper_move + turn_cost + bend_penalty
            nxt = (nc, nr, new_d)

            if new_g < g_costs.get(nxt, math.inf):
                g_costs[nxt] = new_g
                came_from[nxt] = curr
                h = (abs(goal[0] - nc) + abs(goal[1] - nr)) * settings.cost_jumper_move
                heapq.heappush(pq, (new_g + h, new_g, nc, nr, new_d))

    if best_goal_state is None:
        return (math.inf, [])

    # Reconstruct path of holes
    path = []
    curr = best_goal_state
    while curr in came_from:
        path.append((curr[0], curr[1]))
        curr = came_from[curr]
    path.append(start)
    path.reverse()

    # Extract 90° bend points
    bends: list[tuple[int, int]] = []
    for i in range(1, len(path) - 1):
        prev_p = path[i - 1]
        p = path[i]
        nxt_p = path[i + 1]
        d1 = (p[0] - prev_p[0], p[1] - prev_p[1])
        d2 = (nxt_p[0] - p[0], nxt_p[1] - p[1])
        if d1 != d2:
            bends.append(p)

    return (best_cost, bends)


def route_jumper(
    g1_terminals: list[tuple[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int]]], int]],
    g2_terminals: list[tuple[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int]]], int]],
    obstacle_holes: set[tuple[int, int]],
    existing_jumpers: list[Any],
    all_pin_holes: set[tuple[int, int]],
    config: BoardConfig,
    settings: AutoConnectSettings
) -> tuple[int, tuple[int, int], tuple[int, int], list[tuple[int, int]], list[tuple[tuple[int, int], tuple[int, int]]]]:
    """
    Finds the lowest-cost jumper between g1_terminals and g2_terminals.
    Rules:
    - Jumpers cannot start or end on a hole with a component pin!
    - Jumper bodies must NOT touch component pins, pass over them, or run between neighboring pins.
    - If length <= 5 units: direct straight jumper with bends = [], only if clear of all pins.
    - If length > 5 units: perfectly horizontal or vertical with 90° bends.
    - If simple straight/L-routes hit component pins, routes around component pins using A* pathfinding.
    - Each crossing with an existing/planned jumper adds settings.cost_jumper_cross (100).
    Returns (cost, start_hole, end_hole, bends, extra_solder_segments).
    """
    best_cost = math.inf
    best_start = (0, 0)
    best_goal = (0, 0)
    best_bends: list[tuple[int, int]] = []
    best_extra_solder: list[tuple[tuple[int, int], tuple[int, int]]] = []

    if not g1_terminals or not g2_terminals:
        return (math.inf, best_start, best_goal, [], [])

    j_start_cost = (len(existing_jumpers) + 1) * settings.cost_jumper_start

    g1_sorted = sorted(g1_terminals, key=lambda t: t[2])
    g2_sorted = sorted(g2_terminals, key=lambda t: t[2])

    for (sc, sr), s_segs, s_cost in g1_sorted:
        for (gc, gr), g_segs, g_cost in g2_sorted:
            if (sc, sr) == (gc, gr):
                continue

            dx = abs(gc - sc)
            dy = abs(gr - sr)
            dist_euc = math.hypot(dx, dy)
            dist_man = dx + dy

            # Lower bound pruning: minimum conceivable cost for this terminal pair
            min_move_cost = int(dist_euc) * settings.cost_jumper_move if dist_euc <= 5.0 else dist_man * settings.cost_jumper_move
            lb = s_cost + g_cost + j_start_cost + min_move_cost
            if lb >= best_cost:
                continue

            # Option 1: Direct straight jumper (only if <= 5.0 units AND clear of all component pins)
            if dist_euc <= 5.0:
                if is_straight_segment_clear_of_pins((sc, sr), (gc, gr), all_pin_holes):
                    bends = []
                    cross_cost = count_jumper_crossings((sc, sr), (gc, gr), bends, existing_jumpers, settings.cost_jumper_cross)
                    cost = (
                        j_start_cost +
                        int(dist_euc) * settings.cost_jumper_move +
                        cross_cost +
                        s_cost + g_cost
                    )
                    if cost < best_cost:
                        best_cost = cost
                        best_start = (sc, sr)
                        best_goal = (gc, gr)
                        best_bends = bends
                        best_extra_solder = list(s_segs + g_segs)

            # Option 2: Collinear orthogonal segment (sc == gc or sr == gr)
            if sc == gc or sr == gr:
                if is_straight_segment_clear_of_pins((sc, sr), (gc, gr), all_pin_holes):
                    bends = []
                    cross_cost = count_jumper_crossings((sc, sr), (gc, gr), bends, existing_jumpers, settings.cost_jumper_cross)
                    cost = (
                        j_start_cost +
                        dist_man * settings.cost_jumper_move +
                        cross_cost +
                        s_cost + g_cost
                    )
                    if cost < best_cost:
                        best_cost = cost
                        best_start = (sc, sr)
                        best_goal = (gc, gr)
                        best_bends = bends
                        best_extra_solder = list(s_segs + g_segs)
                else:
                    # Collinear straight line is blocked by component pins -> find path around with A*
                    a_cost, a_bends = find_orthogonal_jumper_path(
                        (sc, sr), (gc, gr), all_pin_holes, obstacle_holes, config, settings
                    )
                    if a_cost < math.inf:
                        cross_cost = count_jumper_crossings((sc, sr), (gc, gr), a_bends, existing_jumpers, settings.cost_jumper_cross)
                        cost = (
                            j_start_cost +
                            a_cost +
                            cross_cost +
                            s_cost + g_cost
                        )
                        if cost < best_cost:
                            best_cost = cost
                            best_start = (sc, sr)
                            best_goal = (gc, gr)
                            best_bends = a_bends
                            best_extra_solder = list(s_segs + g_segs)

            # Option 3: 90° L-route (1 bend)
            else:
                bend_opts = [(sc, gr), (gc, sr)]
                found_l_route = False

                for bend in bend_opts:
                    if not config.is_valid_hole(*bend) or bend in all_pin_holes:
                        continue
                    if not is_straight_segment_clear_of_pins((sc, sr), bend, all_pin_holes):
                        continue
                    if not is_straight_segment_clear_of_pins(bend, (gc, gr), all_pin_holes):
                        continue

                    found_l_route = True
                    b_cross_cost = count_jumper_crossings((sc, sr), (gc, gr), [bend], existing_jumpers, settings.cost_jumper_cross)
                    b_cost = (
                        j_start_cost +
                        dist_man * settings.cost_jumper_move +
                        1 * settings.cost_jumper_turn +
                        b_cross_cost +
                        s_cost + g_cost
                    )
                    if bend in obstacle_holes:
                        b_cost += 500  # Penalty for bending on an obstacle hole

                    if b_cost < best_cost:
                        best_cost = b_cost
                        best_start = (sc, sr)
                        best_goal = (gc, gr)
                        best_bends = [bend]
                        best_extra_solder = list(s_segs + g_segs)

                # Option 4: If 1-bend L-routes are blocked by component pins, use A* to go around them
                if not found_l_route:
                    a_cost, a_bends = find_orthogonal_jumper_path(
                        (sc, sr), (gc, gr), all_pin_holes, obstacle_holes, config, settings
                    )
                    if a_cost < math.inf:
                        cross_cost = count_jumper_crossings((sc, sr), (gc, gr), a_bends, existing_jumpers, settings.cost_jumper_cross)
                        cost = (
                            j_start_cost +
                            a_cost +
                            cross_cost +
                            s_cost + g_cost
                        )
                        if cost < best_cost:
                            best_cost = cost
                            best_start = (sc, sr)
                            best_goal = (gc, gr)
                            best_bends = a_bends
                            best_extra_solder = list(s_segs + g_segs)

    return (best_cost, best_start, best_goal, best_bends, best_extra_solder)


def route_multi_hop_hybrid(
    start_holes: set[tuple[int, int]],
    goal_holes: set[tuple[int, int]],
    all_pin_holes: set[tuple[int, int]],
    obstacle_holes: set[tuple[int, int]],
    existing_jumpers: list[Any],
    config: BoardConfig,
    settings: AutoConnectSettings,
    max_jumpers: int = 4
) -> tuple[int, list[tuple[tuple[int, int], tuple[int, int]]], list[dict[str, Any]]] | None:
    """
    Finds the optimal alternating hybrid path (solder -> jumper -> solder -> jumper -> solder...)
    connecting start_holes to goal_holes, alternating as many times as needed to minimize cost.
    For every jumper added, increases the jumper start cost multiplier by one.
    Returns (total_cost, solder_segments, planned_jumpers) or None if unreachable.
    """
    if not start_holes or not goal_holes:
        return None

    if start_holes.intersection(goal_holes):
        return (0, [], [])

    existing_j_count = len(existing_jumpers)
    DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]

    def get_jumper_landings(c: int, r: int) -> set[tuple[int, int]]:
        landings = set()
        # 1. Hops directly to/near goal holes
        for gc, gr in goal_holes:
            if (gc, gr) not in all_pin_holes and (gc, gr) not in obstacle_holes:
                landings.add((gc, gr))
            for dc, dr in DIRS:
                adj = (gc + dc, gr + dr)
                if config.is_valid_hole(*adj) and adj not in all_pin_holes and adj not in obstacle_holes:
                    landings.add(adj)

        # 2. Obstacle-clearing hops along cardinal directions
        for dc, dr in DIRS:
            hit_obstacle = False
            for step in range(1, 20):
                nc, nr = c + dc * step, r + dr * step
                if not config.is_valid_hole(nc, nr):
                    break
                if (nc, nr) in obstacle_holes or (nc, nr) in all_pin_holes:
                    hit_obstacle = True
                elif hit_obstacle:
                    if (nc, nr) not in all_pin_holes and (nc, nr) not in obstacle_holes:
                        landings.add((nc, nr))
                    break

        # 3. Direct short hops (<= 5 units) towards goal
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if dx == 0 and dy == 0:
                    continue
                if math.hypot(dx, dy) <= 5.0:
                    nc, nr = c + dx, r + dy
                    if config.is_valid_hole(nc, nr) and (nc, nr) not in obstacle_holes and (nc, nr) not in all_pin_holes:
                        min_curr = min(abs(c - gc) + abs(r - gr) for gc, gr in goal_holes)
                        min_nxt = min(abs(nc - gc) + abs(nr - gr) for gc, gr in goal_holes)
                        if min_nxt < min_curr:
                            landings.add((nc, nr))

        return landings

    # Priority queue: (f_score, g_cost, c, r, dir_idx, j_used)
    pq: list[tuple[int, int, int, int, int, int]] = []
    g_costs: dict[tuple[int, int, int, int], int] = {}
    came_from: dict[tuple[int, int, int, int], tuple[str, tuple[int, int, int, int], Any]] = {}

    min_move_step = min(settings.cost_solder_move, settings.cost_jumper_move)

    def hybrid_h(c: int, r: int, j_u: int) -> int:
        d_man = min(abs(c - gc) + abs(r - gr) for gc, gr in goal_holes)
        if j_u >= max_jumpers:
            return d_man * settings.cost_solder_move
        return (d_man // 2) * min_move_step

    for sc, sr in start_holes:
        state = (sc, sr, -1, 0)
        g_costs[state] = 0
        heapq.heappush(pq, (hybrid_h(sc, sr, 0), 0, sc, sr, -1, 0))

    best_goal_state = None
    best_cost = math.inf

    while pq:
        f, g, c, r, d, j_used = heapq.heappop(pq)
        curr = (c, r, d, j_used)

        if g > g_costs.get(curr, math.inf):
            continue

        if (c, r) in goal_holes:
            best_goal_state = curr
            best_cost = g
            break

        # 1. Solder Move: step 1 hole along grid on solder layer (bottom)
        for nd, (dc, dr) in enumerate(DIRS):
            nc, nr = c + dc, r + dr
            if not config.is_valid_hole(nc, nr):
                continue
            if (nc, nr) in obstacle_holes:
                continue
            if (nc, nr) in all_pin_holes and (nc, nr) not in goal_holes and (nc, nr) not in start_holes:
                continue

            turn_cost = settings.cost_solder_turn if (d != -1 and nd != d) else 0
            new_g = g + settings.cost_solder_move + turn_cost
            nxt = (nc, nr, nd, j_used)

            if new_g < g_costs.get(nxt, math.inf):
                g_costs[nxt] = new_g
                came_from[nxt] = ("solder", curr, ((c, r), (nc, nr)))
                heapq.heappush(pq, (new_g + hybrid_h(nc, nr, j_used), new_g, nc, nr, nd, j_used))

        # 2. Jumper Hop: launch a jumper wire on top layer
        if (c, r) not in all_pin_holes and j_used < max_jumpers:
            # Jumper start cost multiplier increases by one for every jumper added!
            j_multiplier = existing_j_count + j_used + 1
            j_start_cost = j_multiplier * settings.cost_jumper_start

            landings = get_jumper_landings(c, r)
            for jc, jr in landings:
                if (jc, jr) == (c, r):
                    continue

                dx = abs(jc - c)
                dy = abs(jr - r)
                dist_euc = math.hypot(dx, dy)
                dist_man = dx + dy

                j_valid = False
                j_bends: list[tuple[int, int]] = []
                j_move_cost = 0

                # Option A: Direct straight jumper (<= 5.0 units)
                if dist_euc <= 5.0 and is_straight_segment_clear_of_pins((c, r), (jc, jr), all_pin_holes):
                    j_valid = True
                    j_bends = []
                    j_move_cost = int(dist_euc) * settings.cost_jumper_move
                # Option B: Collinear orthogonal
                elif c == jc or r == jr:
                    if is_straight_segment_clear_of_pins((c, r), (jc, jr), all_pin_holes):
                        j_valid = True
                        j_bends = []
                        j_move_cost = dist_man * settings.cost_jumper_move
                # Option C: 1-bend L-route
                else:
                    for bend in [(c, jr), (jc, r)]:
                        if config.is_valid_hole(*bend) and bend not in all_pin_holes:
                            if is_straight_segment_clear_of_pins((c, r), bend, all_pin_holes) and is_straight_segment_clear_of_pins(bend, (jc, jr), all_pin_holes):
                                j_valid = True
                                j_bends = [bend]
                                j_move_cost = dist_man * settings.cost_jumper_move + settings.cost_jumper_turn
                                break

                if j_valid:
                    cross_cost = count_jumper_crossings(
                        (c, r), (jc, jr), j_bends, existing_jumpers, settings.cost_jumper_cross
                    )
                    j_total_cost = j_start_cost + j_move_cost + cross_cost
                    new_g = g + j_total_cost
                    nxt = (jc, jr, -1, j_used + 1)

                    if new_g < g_costs.get(nxt, math.inf):
                        g_costs[nxt] = new_g
                        j_info = {
                            "start": (c, r),
                            "end": (jc, jr),
                            "bends": j_bends,
                            "side": "top"
                        }
                        came_from[nxt] = ("jumper", curr, j_info)
                        heapq.heappush(pq, (new_g + hybrid_h(jc, jr, j_used + 1), new_g, jc, jr, -1, j_used + 1))

    if best_goal_state is None:
        return None

    # Reconstruct solder segments and jumpers
    planned_solders: list[tuple[tuple[int, int], tuple[int, int]]] = []
    planned_jumpers: list[dict[str, Any]] = []

    curr = best_goal_state
    while curr in came_from:
        act_type, prev_state, data = came_from[curr]
        if act_type == "solder":
            planned_solders.append(data)
        elif act_type == "jumper":
            planned_jumpers.append(data)
        curr = prev_state

    planned_solders.reverse()
    planned_jumpers.reverse()

    return (best_cost, planned_solders, planned_jumpers)


def route_single_group_internal(
    targets: list[AutoConnectTarget],
    obstacles: set[tuple[int, int]],
    active_jumpers_for_crossings: list[Any],
    all_pin_holes: set[tuple[int, int]],
    config: BoardConfig,
    settings: AutoConnectSettings,
    group_color: str = "#00e6ff"
) -> dict[str, Any]:
    """
    Connects a single group of conductors together into a single conductive net.
    Uses MST (Prim's) with solder paths and jumpers, avoiding all obstacles and pin holes for jumper terminals.
    """
    if len(targets) < 2:
        return {
            "success": False,
            "solder_segments": [],
            "jumpers": [],
            "total_cost": 0,
            "message": "Select at least 2 conductors to connect."
        }

    # Initialize connected subgroups
    subgroups: list[set[tuple[int, int]]] = [set(t.holes) for t in targets]

    # Merge subgroups that already share holes
    merged_subgroups: list[set[tuple[int, int]]] = []
    while subgroups:
        first = subgroups.pop(0)
        has_overlap = True
        while has_overlap:
            has_overlap = False
            for i in range(len(subgroups) - 1, -1, -1):
                if first.intersection(subgroups[i]):
                    first.update(subgroups.pop(i))
                    has_overlap = True
        merged_subgroups.append(first)

    if len(merged_subgroups) <= 1:
        return {
            "success": True,
            "solder_segments": [],
            "jumpers": [],
            "total_cost": 0,
            "message": "Conductors in this group are already electrically connected!"
        }

    planned_solder_segments: list[tuple[tuple[int, int], tuple[int, int]]] = []
    planned_jumpers: list[dict[str, Any]] = []
    total_cost = 0

    while len(merged_subgroups) > 1:
        best_link = None
        best_link_cost = math.inf
        best_g1_idx = -1
        best_g2_idx = -1

        for i in range(len(merged_subgroups)):
            for j in range(i + 1, len(merged_subgroups)):
                g1 = merged_subgroups[i]
                g2 = merged_subgroups[j]

                # 1. Try Solder Path
                s_cost, s_path = route_solder_path(g1, g2, obstacles, config, settings)

                # 2. Try 1-Jumper Hybrid Path
                t1 = get_jumper_terminals_for_group(g1, all_pin_holes, obstacles, config, settings)
                t2 = get_jumper_terminals_for_group(g2, all_pin_holes, obstacles, config, settings)
                j_cost, j_start, j_goal, j_bends, j_extra_solder = route_jumper(
                    t1, t2, obstacles, active_jumpers_for_crossings, all_pin_holes, config, settings
                )

                # 3. Try Multi-Hop Alternating Hybrid (solder -> jumper -> solder -> jumper -> solder...)
                m_res = route_multi_hop_hybrid(
                    g1, g2, all_pin_holes, obstacles, active_jumpers_for_crossings, config, settings
                )

                # Compare all candidates to pick the lowest cost
                cand_cost = math.inf
                cand_link = None

                if s_cost < cand_cost:
                    cand_cost = s_cost
                    cand_link = ("solder", s_path)

                if j_cost < cand_cost:
                    cand_cost = j_cost
                    cand_link = ("jumper", j_start, j_goal, j_bends, j_extra_solder)

                if m_res is not None and m_res[0] < cand_cost:
                    cand_cost = m_res[0]
                    cand_link = ("multihop", m_res[1], m_res[2])

                if cand_cost < best_link_cost:
                    best_link_cost = cand_cost
                    best_link = cand_link
                    best_g1_idx = i
                    best_g2_idx = j

        if best_link is None or best_link_cost == math.inf:
            return {
                "success": False,
                "solder_segments": planned_solder_segments,
                "jumpers": planned_jumpers,
                "total_cost": total_cost,
                "message": "Unable to connect conductors: path is completely blocked by obstacles."
            }

        g1 = merged_subgroups[best_g1_idx]
        g2 = merged_subgroups.pop(best_g2_idx)
        g1.update(g2)

        if best_link[0] == "solder":
            path = best_link[1]
            for idx in range(len(path) - 1):
                seg = (path[idx], path[idx + 1])
                planned_solder_segments.append(seg)
                g1.add(path[idx])
                g1.add(path[idx + 1])
        elif best_link[0] == "multihop":
            m_solders = best_link[1]
            m_jumpers = best_link[2]
            for seg in m_solders:
                planned_solder_segments.append(seg)
                g1.add(seg[0])
                g1.add(seg[1])
            for j_data in m_jumpers:
                new_jumper = {
                    "start": j_data["start"],
                    "end": j_data["end"],
                    "bends": j_data.get("bends", []),
                    "side": "top",
                    "color": group_color
                }
                planned_jumpers.append(new_jumper)
                active_jumpers_for_crossings.append(new_jumper)
                g1.add(j_data["start"])
                g1.add(j_data["end"])
        else:
            _, j_start, j_goal, j_bends, j_extra_solder = best_link
            for seg in j_extra_solder:
                planned_solder_segments.append(seg)
                g1.add(seg[0])
                g1.add(seg[1])

            new_jumper = {
                "start": j_start,
                "end": j_goal,
                "bends": j_bends,
                "side": "top",
                "color": group_color
            }
            planned_jumpers.append(new_jumper)
            active_jumpers_for_crossings.append(new_jumper)
            g1.add(j_start)
            g1.add(j_goal)

        total_cost += int(best_link_cost)

    return {
        "success": True,
        "solder_segments": planned_solder_segments,
        "jumpers": planned_jumpers,
        "total_cost": total_cost,
        "message": f"Successfully connected {len(targets)} conductors (Cost: {total_cost})."
    }


def connect_targets(
    targets: list[AutoConnectTarget],
    config: BoardConfig,
    solder_mgr: SolderManager,
    jumpers: list[JumperWire],
    components: list[PlacedComponent],
    registry: Any,
    settings: AutoConnectSettings,
    color: str = "#00e6ff"
) -> dict[str, Any]:
    """
    Connects all selected targets into a single conductive net with minimal cost.
    """
    if len(targets) < 2:
        return {
            "success": False,
            "solder_segments": [],
            "jumpers": [],
            "total_cost": 0,
            "message": "Select at least 2 conductors to connect."
        }

    all_target_holes: set[tuple[int, int]] = set()
    for t in targets:
        all_target_holes.update(t.holes)

    obstacles = get_all_obstacle_holes(
        config, solder_mgr, jumpers, components, registry, all_target_holes
    )

    all_pin_holes: set[tuple[int, int]] = set()
    for comp in components:
        comp_def = registry.get(comp.type_id)
        if comp_def:
            for _, c, r, _ in comp.get_pin_positions(comp_def):
                if config.is_valid_hole(c, r):
                    all_pin_holes.add((c, r))

    active_jumpers_for_crossings = list(jumpers)

    if is_native_available():
        single_grp = AutoConnectGroup(id=0, color=color, targets=targets)
        native_res = solve_groups_native(
            config.cols, config.rows, settings, obstacles, all_pin_holes, active_jumpers_for_crossings, [single_grp]
        )
        if native_res is not None:
            if native_res["success"]:
                total_cost = native_res["total_cost"]
                if not native_res["solder_segments"] and not native_res["jumpers"]:
                    msg = "Conductors in this group are already electrically connected!"
                else:
                    msg = f"Successfully connected {len(targets)} conductors (Cost: {total_cost})."
                return {
                    "success": True,
                    "solder_segments": native_res["solder_segments"],
                    "jumpers": native_res["jumpers"],
                    "total_cost": total_cost,
                    "message": msg,
                }
            return {
                "success": False,
                "solder_segments": [],
                "jumpers": [],
                "total_cost": 0,
                "message": "Unable to connect conductors: path is completely blocked by obstacles.",
            }

    return route_single_group_internal(
        targets=targets,
        obstacles=obstacles,
        active_jumpers_for_crossings=active_jumpers_for_crossings,
        all_pin_holes=all_pin_holes,
        config=config,
        settings=settings,
        group_color=color
    )


def connect_multiple_groups(
    groups: list[AutoConnectGroup],
    config: BoardConfig,
    solder_mgr: SolderManager,
    jumpers: list[JumperWire],
    components: list[PlacedComponent],
    registry: Any,
    settings: AutoConnectSettings
) -> dict[str, Any]:
    """
    Routes connections for multiple conductor groups at the same time,
    ensuring zero intersection or short-circuit between different groups.
    Uses multi-threaded native C++ engine with conflict backjumping and
    rip-up-and-reroute when available, with Python fallback.
    """
    if not groups:
        return {
            "success": False,
            "solder_segments": [],
            "jumpers": [],
            "total_cost": 0,
            "message": "No groups provided for autoconnect."
        }

    for g in groups:
        if len(g.targets) < 2:
            return {
                "success": False,
                "solder_segments": [],
                "jumpers": [],
                "total_cost": 0,
                "message": f"Group #{g.id} has fewer than 2 conductors ({len(g.targets)}). Each group needs at least 2 conductors."
            }

    # All pin holes on the entire board
    all_pin_holes: set[tuple[int, int]] = set()
    for comp in components:
        comp_def = registry.get(comp.type_id)
        if comp_def:
            for _, c, r, _ in comp.get_pin_positions(comp_def):
                if config.is_valid_hole(c, r):
                    all_pin_holes.add((c, r))

    # Base obstacles: any existing board conductor not belonging to ANY group
    all_groups_target_holes: set[tuple[int, int]] = set()
    for g in groups:
        all_groups_target_holes.update(g.all_holes())

    base_obstacles = get_all_obstacle_holes(
        config, solder_mgr, jumpers, components, registry, all_groups_target_holes
    )

    if is_native_available():
        native_res = solve_groups_native(
            config.cols, config.rows, settings, base_obstacles, all_pin_holes, list(jumpers), groups
        )
        if native_res is not None:
            if native_res["success"]:
                total_cost = native_res["total_cost"]
                return {
                    "success": True,
                    "solder_segments": native_res["solder_segments"],
                    "jumpers": native_res["jumpers"],
                    "total_cost": total_cost,
                    "group_details": native_res["group_details"],
                    "message": f"Successfully connected {len(groups)} groups ({sum(len(g.targets) for g in groups)} conductors) without intersection (Cost: {total_cost}).",
                }
            return {
                "success": False,
                "solder_segments": [],
                "jumpers": [],
                "total_cost": 0,
                "message": "Could not route all groups without intersection. Path is blocked by obstacles.",
            }

    # Pure Python fallback: check permutations / diverse orderings with backjumping
    if len(groups) <= 4:
        perms = list(itertools.permutations(groups))
    else:
        by_targets_bbox = sorted(
            groups,
            key=lambda grp: (len(grp.targets), max((h[0] for h in grp.all_holes()), default=0) - min((h[0] for h in grp.all_holes()), default=0)),
        )
        by_span_asc = sorted(
            groups,
            key=lambda grp: (
                max((h[0] for h in grp.all_holes()), default=0) - min((h[0] for h in grp.all_holes()), default=0)
                + max((h[1] for h in grp.all_holes()), default=0) - min((h[1] for h in grp.all_holes()), default=0)
            ),
        )
        perms = [by_targets_bbox, by_span_asc, list(reversed(by_span_asc))]

    best_result = None
    best_cost = math.inf

    for seed_perm in perms:
        cur_perm = list(seed_perm)
        for attempt in range(min(6, len(groups) + 1)):
            perm_obstacles = set(base_obstacles)
            for g in cur_perm:
                perm_obstacles.update(g.all_holes())

            perm_jumpers_for_crossings = list(jumpers)
            perm_solders: list[tuple[tuple[int, int], tuple[int, int]]] = []
            perm_jumpers: list[dict[str, Any]] = []
            perm_total_cost = 0
            failed_pos = -1
            perm_group_details = []

            for pos, g in enumerate(cur_perm):
                g_obstacles = perm_obstacles - g.all_holes()

                res = route_single_group_internal(
                    targets=g.targets,
                    obstacles=g_obstacles,
                    active_jumpers_for_crossings=perm_jumpers_for_crossings,
                    all_pin_holes=all_pin_holes,
                    config=config,
                    settings=settings,
                    group_color=g.color
                )

                if not res["success"]:
                    failed_pos = pos
                    break

                perm_solders.extend(res["solder_segments"])
                perm_jumpers.extend(res["jumpers"])
                perm_jumpers_for_crossings.extend(res["jumpers"])
                perm_total_cost += res["total_cost"]
                perm_group_details.append({
                    "group_id": g.id,
                    "color": g.color,
                    "cost": res["total_cost"],
                    "solders": res["solder_segments"],
                    "jumpers": res["jumpers"]
                })

                for h1, h2 in res["solder_segments"]:
                    perm_obstacles.add(h1)
                    perm_obstacles.add(h2)
                for j_dict in res["jumpers"]:
                    perm_obstacles.add(j_dict["start"])
                    perm_obstacles.add(j_dict["end"])

            if failed_pos == -1:
                if perm_total_cost < best_cost:
                    best_cost = perm_total_cost
                    best_result = {
                        "success": True,
                        "solder_segments": perm_solders,
                        "jumpers": perm_jumpers,
                        "total_cost": perm_total_cost,
                        "group_details": perm_group_details,
                        "message": f"Successfully connected {len(groups)} groups ({sum(len(g.targets) for g in groups)} conductors) without intersection (Cost: {perm_total_cost})."
                    }
                break

            # Conflict-directed bump
            failed_g = cur_perm.pop(failed_pos)
            cur_perm.insert(0 if attempt % 2 == 0 else failed_pos // 2, failed_g)

    if best_result is not None:
        return best_result

    return {
        "success": False,
        "solder_segments": [],
        "jumpers": [],
        "total_cost": 0,
        "message": "Could not route all groups without intersection. Path is blocked by obstacles."
    }


def extract_connected_pin_groups(
    config: BoardConfig,
    solder_mgr: SolderManager,
    jumpers: list[JumperWire],
    components: list[PlacedComponent],
    registry: Any,
) -> list[AutoConnectGroup]:
    """
    Traces electrical continuity across all solder traces and jumper wires,
    grouping component pins that are shorted together into AutoConnectGroup objects.
    Only nets spanning 2 or more distinct component pin holes are included.
    """
    # 1. Build conductive adjacency graph across holes
    adj: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)

    for trace in solder_mgr.traces:
        if trace.segments:
            for h1, h2 in trace.segments:
                adj[h1].add(h2)
                adj[h2].add(h1)
            if trace.holes:
                anchor = trace.holes[0]
                for h in trace.holes[1:]:
                    if not adj[h]:
                        adj[anchor].add(h)
                        adj[h].add(anchor)
        elif len(trace.holes) >= 2:
            anchor = trace.holes[0]
            for h in trace.holes[1:]:
                adj[anchor].add(h)
                adj[h].add(anchor)

    for j in jumpers:
        s = (j.start_col, j.start_row)
        e = (j.end_col, j.end_row)
        adj[s].add(e)
        adj[e].add(s)

    # 2. Index component pins by board hole
    pins_by_hole: dict[tuple[int, int], list[tuple[PlacedComponent, str]]] = defaultdict(list)
    for comp in components:
        comp_def = registry.get(comp.type_id)
        if not comp_def:
            continue
        for pname, pc, pr, _ in comp.get_pin_positions(comp_def):
            if config.is_valid_hole(pc, pr):
                pins_by_hole[(pc, pr)].append((comp, pname))

    # 3. Traverse connected components via BFS
    visited: set[tuple[int, int]] = set()
    raw_nets: list[list[AutoConnectTarget]] = []

    for start_hole in sorted(pins_by_hole.keys()):
        if start_hole in visited:
            continue

        comp_holes: set[tuple[int, int]] = set()
        queue = deque([start_hole])
        visited.add(start_hole)

        while queue:
            curr = queue.popleft()
            comp_holes.add(curr)
            for nxt in adj.get(curr, ()):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)

        # Collect unique pin holes belonging to this conductive net
        net_pin_holes = sorted(h for h in comp_holes if h in pins_by_hole)
        if len(net_pin_holes) < 2:
            continue

        targets: list[AutoConnectTarget] = []
        for h in net_pin_holes:
            entries = pins_by_hole[h]
            labels = []
            for comp, pname in entries:
                comp_name = comp.label.strip() if comp.label else comp.type_id
                labels.append(f"{comp_name} [{pname}]")
            targets.append(
                AutoConnectTarget(
                    target_type="pin",
                    label=" / ".join(labels),
                    holes={h},
                    center_hole=h,
                    pin_name=entries[0][1],
                )
            )
        raw_nets.append(targets)

    # Sort groups deterministically by their top-leftmost pin hole
    raw_nets.sort(key=lambda t_list: (min(t.center_hole[1] for t in t_list), min(t.center_hole[0] for t in t_list)))

    groups: list[AutoConnectGroup] = []
    for idx, targets in enumerate(raw_nets):
        groups.append(
            AutoConnectGroup(
                id=idx + 1,
                color=get_group_color(idx),
                targets=targets,
            )
        )
    return groups

