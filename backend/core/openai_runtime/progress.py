from __future__ import annotations


class ClassicProgressAccumulator:
    """Maintain one replaceable Classic executor progress block.

    Classic executor progress arrives as cumulative snapshots. Prefix growth is
    appended as a delta; divergent snapshots replace the previous progress block
    instead of being appended and shown twice.
    """

    def __init__(self) -> None:
        self.snapshot = ""
        self.block_start: int | None = None

    def apply(self, full_text: str, snapshot: str, *, reset: bool = False) -> str:
        snapshot = str(snapshot or "")
        if not snapshot:
            return full_text

        if reset or not self.snapshot or self.block_start is None:
            return self._append_new_block(full_text, snapshot)

        if snapshot.startswith(self.snapshot):
            delta = snapshot[len(self.snapshot) :]
            self.snapshot = snapshot
            return full_text + delta if delta else full_text

        prefix = full_text[: self.block_start]
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n\n"
        self.snapshot = snapshot
        return prefix + snapshot

    def _append_new_block(self, full_text: str, snapshot: str) -> str:
        prefix = full_text
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n\n"
        self.block_start = len(prefix)
        self.snapshot = snapshot
        return prefix + snapshot


__all__ = ["ClassicProgressAccumulator"]
