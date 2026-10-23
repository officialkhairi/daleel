"""Citation markers in a streamed answer. The model writes [n] after claims; tokens arrive in
arbitrary pieces ("[", "1", "]"), so a possible marker is held back until it is complete."""

import re
from dataclasses import dataclass, field

# "[1]", "[1, 3]", "[1،3]" (Arabic comma); sources are numbered from 1, so "[0]" (as in code)
# is not a marker. Small models sometimes echo the prompt's tag instead ("[source n="1"]",
# "[Source 2]"); those are markers too and are rewritten to the plain form. Anything else in
# brackets is ordinary text.
_N = r"[1-9]\d?"
_Q = "[\"']?"
_MARKER = re.compile(
    rf"\[\s*(?:source\s*(?:n\s*=\s*)?{_Q})?({_N}(?:\s*[,،]\s*{_N})*){_Q}\s*\]", re.IGNORECASE
)
# A prefix that could still grow into a marker.
_PARTIAL = re.compile(
    rf"\[\s*(?:(?:s|so|sou|sour|sourc)$|source\s*(?:n\s*(?:=\s*{_Q})?)?)?"
    rf"({_N}(\s*[,،]\s*({_N})?)*{_Q})?\s*$",
    re.IGNORECASE,
)
_MAX_HELD = 24


@dataclass
class CitationFilter:
    """Feed it text as it streams; it returns text safe to show now and the source numbers
    cited for the first time. Markers for sources that were never given to the model are
    removed and counted in `dropped`."""

    valid: set[int]
    cited: list[int] = field(default_factory=list)
    dropped: int = 0
    _held: str = ""

    def _rewrite(self, match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", match.group(1))]
        kept = [n for n in numbers if n in self.valid]
        self.dropped += len(numbers) - len(kept)
        for n in kept:
            if n not in self.cited:
                self.cited.append(n)
        return "".join(f"[{n}]" for n in kept)

    def _process(self, text: str) -> tuple[str, list[int]]:
        before = len(self.cited)
        out = _MARKER.sub(self._rewrite, text)
        return out, self.cited[before:]

    def feed(self, chunk: str) -> tuple[str, list[int]]:
        text = self._held + chunk
        self._held = ""
        start = text.rfind("[")
        if start != -1 and len(text) - start <= _MAX_HELD and _PARTIAL.match(text, start):
            text, self._held = text[:start], text[start:]
        return self._process(text)

    def flush(self) -> tuple[str, list[int]]:
        text, self._held = self._held, ""
        return self._process(text)
