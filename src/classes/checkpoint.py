import json
from pathlib import Path # path construction methods

class Checkpoint:
    """Records which date chunks are already on disk, so a run can resume."""

    def __init__(self, path: Path):
        self.path = path
        self.done: set[str] = set()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.done = set(payload.get("completed_chunks", []))
        except (json.JSONDecodeError, OSError) as error:
            print(f"Aviso: não foi possível ler o checkpoint ({error}). Começando do zero.")
            self.done = set()

    def mark(self, key: str) -> None:
        self.done.add(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"completed_chunks": sorted(self.done)}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def reset(self) -> None:
        self.done = set()
        self.path.unlink(missing_ok=True)

