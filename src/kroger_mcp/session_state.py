"""
Session state tracking for enforcing tool calling requirements.

Tracks which tools have been called in the current session to enforce
workflow requirements (e.g., must check pantry attention before adding to cart).
"""

from typing import Dict, Set
from datetime import datetime, timedelta


class SessionStateManager:
    """
    Manages session state for MCP tool calling requirements.

    Session = single conversation/MCP connection. State resets on disconnect.
    """

    def __init__(self):
        # Dict[session_id: str, Set[tool_name: str]]
        self._tool_calls: Dict[str, Set[str]] = {}
        # Track last activity for cleanup
        self._last_activity: Dict[str, datetime] = {}

    def mark_tool_called(self, session_id: str, tool_name: str) -> None:
        """Record that a tool was called in this session."""
        if session_id not in self._tool_calls:
            self._tool_calls[session_id] = set()

        self._tool_calls[session_id].add(tool_name)
        self._last_activity[session_id] = datetime.now()

    def was_tool_called(self, session_id: str, tool_name: str) -> bool:
        """Check if a tool has been called in this session."""
        if session_id not in self._tool_calls:
            return False
        return tool_name in self._tool_calls[session_id]

    def reset_session(self, session_id: str) -> None:
        """Clear all state for a session."""
        self._tool_calls.pop(session_id, None)
        self._last_activity.pop(session_id, None)

    def cleanup_stale_sessions(self, max_age_hours: int = 24) -> None:
        """Remove sessions with no activity in max_age_hours."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        stale_sessions = [
            sid
            for sid, last_active in self._last_activity.items()
            if last_active < cutoff
        ]
        for sid in stale_sessions:
            self.reset_session(sid)


# Global singleton instance
_session_manager = SessionStateManager()


def get_session_manager() -> SessionStateManager:
    """Get the global session state manager instance."""
    return _session_manager
