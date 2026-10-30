"""Simple agent roster management - just a list of agent names."""

import json
from pathlib import Path
from filelock import FileLock, Timeout

from ...logging_config import logger


class AgentRoster:
    """Simple roster that stores agent names in a JSON file."""

    def __init__(self, roster_path: Path):
        self._roster_path = roster_path
        self._agents: list[str] = []
        self.load()

    def load(self) -> None:
        """Load agent names from roster.json."""
        if self._roster_path.exists():
            try:
                with open(self._roster_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._agents = [str(name) for name in data]
            except Exception as exc:
                logger.warning(f"Failed to load roster.json: {exc}")
                self._agents = []
        else:
            self._agents = []
            self.save()

    '''def save(self) -> None:
        """Save agent names to roster.json with file locking."""
        max_retries = 5
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                self._roster_path.parent.mkdir(parents=True, exist_ok=True)

                # Open file and acquire exclusive lock
                with open(self._roster_path, 'w') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    try:
                        json.dump(self._agents, f, indent=2)
                        return
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            except BlockingIOError:
                # Lock is held by another process
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.warning("Failed to acquire lock on roster.json after retries")
            except Exception as exc:
                logger.warning(f"Failed to save roster.json: {exc}")
                break'''

    def save(self) -> None:
        """Save agent names using a cross-platform file lock."""

        self._roster_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        lock_path = self._roster_path.with_name(
            self._roster_path.name + ".lock"
        )
        temp_path = self._roster_path.with_name(
            self._roster_path.name + ".tmp"
        )

        try:
            with FileLock(str(lock_path), timeout=5):
                try:
                    temp_path.write_text(
                        json.dumps(self._agents, indent=2),
                        encoding="utf-8"
                    )
                    temp_path.replace(self._roster_path)
                finally:
                    temp_path.unlink(missing_ok=True)

        except Timeout:
            logger.warning("Failed to acquire roster lock")

        except Exception as exc:
            logger.warning(f"Failed to save roster: {exc}")

    def add_agent(self, agent_name: str) -> None:
        """Add an agent to the roster if not already present."""
        if agent_name not in self._agents:
            self._agents.append(agent_name)
            self.save()

    def get_agents(self) -> list[str]:
        """Get list of all agent names."""
        return list(self._agents)

    def clear(self) -> None:
        """Clear the agent roster."""
        self._agents = []
        try:
            if self._roster_path.exists():
                self._roster_path.unlink()
            logger.info("Cleared agent roster")
        except Exception as exc:
            logger.warning(f"Failed to clear roster.json: {exc}")


_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_ROSTER_PATH = _DATA_DIR / "execution_agents" / "roster.json"

_agent_roster = AgentRoster(_ROSTER_PATH)


def get_agent_roster() -> AgentRoster:
    """Get the singleton roster instance."""
    return _agent_roster
