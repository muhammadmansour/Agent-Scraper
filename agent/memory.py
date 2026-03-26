"""
Agent memory — persistent storage for decisions, patterns, and session history.

Saved to output/agent_memory.json so the agent can learn across sessions.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


MEMORY_FILE = Path("output") / "agent_memory.json"


class AgentMemory:
    """
    Persistent memory for the LLM agent.

    Stores:
    - session_log: list of (timestamp, role, content) entries
    - decisions: what the agent chose and why
    - patterns: learned observations (e.g., "ncar rate-limits after 50 pages")
    """

    def __init__(self):
        self.sessions: list[dict] = []
        self.decisions: list[dict] = []
        self.patterns: list[dict] = []
        self._load()

    def _load(self) -> None:
        """Load memory from disk if it exists."""
        if MEMORY_FILE.exists():
            try:
                data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                self.sessions = data.get("sessions", [])
                self.decisions = data.get("decisions", [])
                self.patterns = data.get("patterns", [])
                print(f"  [memory] Loaded {len(self.decisions)} decisions, {len(self.patterns)} patterns")
            except (json.JSONDecodeError, KeyError):
                print("  [memory] Corrupted memory file — starting fresh")

    def _save(self) -> None:
        """Persist memory to disk."""
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "sessions": self.sessions[-50:],     # keep last 50 sessions
            "decisions": self.decisions[-200:],   # keep last 200 decisions
            "patterns": self.patterns[-50:],      # keep last 50 patterns
        }
        MEMORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def log_session_start(self) -> None:
        """Record that a new agent session started."""
        entry = {
            "event": "session_start",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.sessions.append(entry)
        self._save()

    def log_session_end(self, reason: str) -> None:
        """Record session end with reason."""
        entry = {
            "event": "session_end",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        self.sessions.append(entry)
        self._save()

    def log_decision(self, tool_name: str, args: dict, reasoning: str, result_summary: str) -> None:
        """Record a tool decision the agent made."""
        self.decisions.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "args": args,
            "reasoning": reasoning,
            "result": result_summary,
        })
        self._save()

    def add_pattern(self, pattern: str, source: str = "") -> None:
        """Record a learned pattern (e.g., rate-limit behavior)."""
        self.patterns.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "pattern": pattern,
        })
        self._save()

    def get_context_for_llm(self) -> str:
        """
        Format memory into a string the LLM can use.

        Returns recent decisions and known patterns.
        """
        lines = []

        if self.patterns:
            lines.append("Known patterns:")
            for p in self.patterns[-10:]:
                src = f"[{p['source']}] " if p.get("source") else ""
                lines.append(f"  - {src}{p['pattern']}")
            lines.append("")

        if self.decisions:
            lines.append("Recent decisions (last 5):")
            for d in self.decisions[-5:]:
                lines.append(f"  - {d['tool']}({d['args']}) → {d['result']}")
            lines.append("")

        return "\n".join(lines)
