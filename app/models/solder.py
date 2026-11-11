"""
Solder trace and connectivity models with deletion and connected component tracking.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

@dataclass(eq=False)
class SolderTrace:
    """
    A continuous solder trace/bridge consisting of an ordered or connected set of holes.
    Separate traces do not short/connect unless explicitly drawn to share a hole.
    """
    id: int
    holes: list[tuple[int, int]] = field(default_factory=list) # (col, row)
    segments: list[tuple[tuple[int, int], tuple[int, int]]] = field(default_factory=list)

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, SolderTrace) and self.id == other.id

    def contains_hole(self, col: int, row: int) -> bool:
        return (col, row) in self.holes

    def add_segment(self, h1: tuple[int, int], h2: tuple[int, int]):
        if h1 not in self.holes:
            self.holes.append(h1)
        if h2 not in self.holes:
            self.holes.append(h2)

        seg = (h1, h2) if h1 <= h2 else (h2, h1)
        if seg not in self.segments:
            self.segments.append(seg)

    def add_single_hole(self, hole: tuple[int, int]):
        if hole not in self.holes:
            self.holes.append(hole)

    def remove_hole(self, col: int, row: int) -> bool:
        """Removes hole and incident segments. Returns True if hole was present."""
        target = (col, row)
        if target not in self.holes:
            return False

        self.holes.remove(target)
        self.segments = [s for s in self.segments if s[0] != target and s[1] != target]
        return True


class SolderManager:
    """Manages all solder traces on the perfboard back side."""
    def __init__(self):
        self.traces: list[SolderTrace] = []
        self._next_id = 1

    def clear(self):
        self.traces.clear()
        self._next_id = 1

    def find_trace_with_hole(self, col: int, row: int) -> Optional[SolderTrace]:
        for trace in self.traces:
            if trace.contains_hole(col, row):
                return trace
        return None

    def create_trace(self) -> SolderTrace:
        trace = SolderTrace(id=self._next_id)
        self._next_id += 1
        self.traces.append(trace)
        return trace

    def merge_traces(self, t1: SolderTrace, t2: SolderTrace) -> SolderTrace:
        if t1 is t2:
            return t1
        for h in t2.holes:
            if h not in t1.holes:
                t1.holes.append(h)
        for s in t2.segments:
            if s not in t1.segments:
                t1.segments.append(s)
        if t2 in self.traces:
            self.traces.remove(t2)
        return t1

    def connect_holes(self, h1: tuple[int, int], h2: tuple[int, int]):
        """Connects h1 and h2. If either belongs to an existing trace, attaches to it."""
        t1 = self.find_trace_with_hole(*h1)
        t2 = self.find_trace_with_hole(*h2)

        if t1 and t2:
            trace = self.merge_traces(t1, t2)
            trace.add_segment(h1, h2)
        elif t1:
            t1.add_segment(h1, h2)
        elif t2:
            t2.add_segment(h1, h2)
        else:
            trace = self.create_trace()
            trace.add_segment(h1, h2)

    def delete_at_hole(self, col: int, row: int) -> bool:
        """
        Deletes solder at (col, row), splitting any disconnected remaining parts of the trace.
        Returns True if something was deleted.
        """
        trace = self.find_trace_with_hole(col, row)
        if not trace:
            return False

        trace.remove_hole(col, row)
        if not trace.holes:
            if trace in self.traces:
                self.traces.remove(trace)
            return True

        # Check if trace is now split into multiple disconnected components
        self._split_trace_if_disconnected(trace)
        return True

    def delete_segment(self, h1: tuple[int, int], h2: tuple[int, int]) -> bool:
        seg = (h1, h2) if h1 <= h2 else (h2, h1)
        for trace in list(self.traces):
            if seg in trace.segments:
                trace.segments.remove(seg)
                self._split_trace_if_disconnected(trace)
                return True
        return False

    def _split_trace_if_disconnected(self, trace: SolderTrace):
        """Splits a trace into multiple traces if it has separated connected components."""
        if not trace.holes:
            if trace in self.traces:
                self.traces.remove(trace)
            return

        # Build adjacency graph
        adj = defaultdict(list)
        for s1, s2 in trace.segments:
            adj[s1].append(s2)
            adj[s2].append(s1)

        visited = set()
        components: list[tuple[set[tuple[int, int]], list[tuple[tuple[int, int], tuple[int, int]]]]] = []

        for h in trace.holes:
            if h not in visited:
                comp_holes = set()
                comp_segments = []
                queue = deque([h])
                visited.add(h)
                comp_holes.add(h)

                while queue:
                    curr = queue.popleft()
                    for neighbor in adj[curr]:
                        s = (curr, neighbor) if curr <= neighbor else (neighbor, curr)
                        if s in trace.segments and s not in comp_segments:
                            comp_segments.append(s)
                        if neighbor not in visited:
                            visited.add(neighbor)
                            comp_holes.add(neighbor)
                            queue.append(neighbor)

                components.append((comp_holes, comp_segments))

        if len(components) <= 1:
            return

        # Replace original trace with first component, create new traces for rest
        self.traces.remove(trace)
        for comp_holes, comp_segs in components:
            new_t = self.create_trace()
            new_t.holes = list(comp_holes)
            new_t.segments = list(comp_segs)

    def get_all_segments(self) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        all_segs = []
        for t in self.traces:
            all_segs.extend(t.segments)
        return all_segs

    def get_all_holes(self) -> set[tuple[int, int]]:
        s = set()
        for t in self.traces:
            s.update(t.holes)
        return s


@dataclass
class ConnectedPinInfo:
    """Metadata describing a component pin electrically connected to a solder path."""
    component_label: str
    component_name: str
    pin_name: str
    col: int
    row: int
    pin_type: str
    via_jumper: bool = False


@dataclass
class SelectedSolderPath:
    """Selection payload for a selected SolderTrace and its connected pins/net."""
    trace: SolderTrace
    direct_pins: list[ConnectedPinInfo] = field(default_factory=list)
    net_only_pins: list[ConnectedPinInfo] = field(default_factory=list)
    net_traces: list[SolderTrace] = field(default_factory=list)
    net_jumpers: list = field(default_factory=list)
    net_holes: set[tuple[int, int]] = field(default_factory=set)

    @property
    def all_pins(self) -> list[ConnectedPinInfo]:
        return [*self.direct_pins, *self.net_only_pins]

