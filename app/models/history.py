"""
Undo/Redo history manager for PerfBoardMaker.
Supports going back and forward up to 200 steps using state snapshots.
"""
from typing import Any, Callable

class HistoryManager:
    def __init__(self, max_depth: int = 200):
        self.max_depth = max_depth
        self.undo_stack: list[dict[str, Any]] = []
        self.redo_stack: list[dict[str, Any]] = []
        self._is_active: bool = False
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, callback: Callable[[], None]):
        self._listeners.append(callback)

    def _notify(self):
        for listener in self._listeners:
            try:
                listener()
            except Exception:
                pass

    def reset(self, initial_state: dict[str, Any]):
        """Resets the history with an initial state snapshot."""
        self.undo_stack = [initial_state]
        self.redo_stack.clear()
        self._notify()

    def push_state(self, state: dict[str, Any]):
        """Records a new state. Clears redo stack. Discards oldest state if over max_depth."""
        if self._is_active:
            return

        # Avoid pushing identical duplicate state back-to-back
        if self.undo_stack and self.undo_stack[-1] == state:
            return

        self.undo_stack.append(state)
        if len(self.undo_stack) > self.max_depth + 1:
            self.undo_stack.pop(0)

        self.redo_stack.clear()
        self._notify()

    def replace_top_state(self, state: dict[str, Any]):
        """Replaces the top state on the undo stack without clearing redo stack or adding a new entry."""
        if self.undo_stack:
            self.undo_stack[-1] = state
            self._notify()

    def can_undo(self) -> bool:
        return len(self.undo_stack) > 1

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def undo(self) -> dict[str, Any] | None:
        """Returns the previous state to restore, or None if cannot undo."""
        if not self.can_undo():
            return None

        self._is_active = True
        try:
            current = self.undo_stack.pop()
            self.redo_stack.append(current)
            prev_state = self.undo_stack[-1]
            return prev_state
        finally:
            self._is_active = False

    def redo(self) -> dict[str, Any] | None:
        """Returns the next state to restore, or None if cannot redo."""
        if not self.can_redo():
            return None

        self._is_active = True
        try:
            next_state = self.redo_stack.pop()
            self.undo_stack.append(next_state)
            return next_state
        finally:
            self._is_active = False
