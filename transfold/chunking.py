from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional


@dataclass
class Segment:
    """A slice of a document that may or may not require translation."""

    index: int
    content: str
    translate: bool = True
    kind: str = "text"
    metadata: dict = field(default_factory=dict)
    translation: Optional[str] = None

    def output(self) -> str:
        return self.translation if self.translation is not None else self.content


@dataclass
class SegmentedDocument:
    segments: List[Segment]

    def merge(self) -> str:
        return "".join(segment.output() for segment in self.segments)


_CODE_FENCE_RE = re.compile(r"^([`~]{3,})(.*)$")
_SENTENCE_RE = re.compile(r".+?(?:[.!?。！？；;](?:\s|$)|$)", re.S)
_PARAGRAPH_SPLIT_RE = re.compile(r"(\n\s*\n)")


def segment_document(
    text: str,
    *,
    strategy: str = "markdown",
    max_chars: int = 4000,
    preserve_code: bool = True,
    preserve_frontmatter: bool = True,
    split_threshold: Optional[int] = None,
) -> SegmentedDocument:
    if strategy != "markdown":
        raise ValueError(f"Unsupported segmentation strategy: {strategy}")

    segments: List[Segment] = []
    index = 0
    remaining = text

    if preserve_frontmatter and remaining.startswith("---"):
        front, rest = _split_front_matter(remaining)
        if front is not None:
            segments.append(
                Segment(index=index, content=front, translate=False, kind="front_matter")
            )
            index += 1
            remaining = rest

    text_segments = _split_markdown_body(
        remaining,
        max_chars=max_chars,
        preserve_code=preserve_code,
        split_threshold=split_threshold,
    )
    for seg in text_segments:
        seg.index = index
        index += 1
        segments.append(seg)

    return SegmentedDocument(segments)


def _split_front_matter(text: str) -> tuple[Optional[str], str]:
    lines = text.splitlines(keepends=True)
    if not lines:
        return None, text

    if not lines[0].strip().startswith("---"):
        return None, text

    collected: List[str] = [lines[0]]
    for idx in range(1, len(lines)):
        collected.append(lines[idx])
        if lines[idx].strip().startswith("---"):
            # include the line following the closing delimiter if blank to preserve spacing
            remainder = "".join(lines[idx + 1 :])
            return "".join(collected), remainder
    return None, text


def _split_markdown_body(
    text: str,
    *,
    max_chars: int,
    preserve_code: bool,
    split_threshold: Optional[int],
) -> List[Segment]:
    lines = text.splitlines(keepends=True)
    length = len(lines)
    idx = 0
    buffer: List[str] = []
    segments: List[Segment] = []
    single_pass = (
        split_threshold is not None
        and split_threshold > 0
        and len(text) <= split_threshold
    )
    effective_limit = max(max_chars, len(text)) if single_pass else max_chars

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        block = "".join(buffer)
        for part in _enforce_max_chars(block, effective_limit):
            segments.append(Segment(index=-1, content=part, translate=True, kind="text"))
        buffer = []

    while idx < length:
        line = lines[idx]
        stripped = line.lstrip()
        fence_match = _CODE_FENCE_RE.match(stripped)
        if preserve_code and fence_match:
            flush_buffer()
            fence = fence_match.group(1)
            code_lines = [line]
            idx += 1
            while idx < length:
                code_lines.append(lines[idx])
                closing = lines[idx].lstrip().startswith(fence)
                idx += 1
                if closing:
                    break
            segments.append(
                Segment(
                    index=-1,
                    content="".join(code_lines),
                    translate=False,
                    kind="code",
                )
            )
            continue

        buffer.append(line)
        idx += 1

    flush_buffer()
    return segments


def _enforce_max_chars(text: str, max_chars: int) -> Iterable[str]:
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    parts: List[str] = []
    tokens = _PARAGRAPH_SPLIT_RE.split(text)
    current = ""

    def append_current() -> None:
        nonlocal current
        if current:
            parts.append(current)
            current = ""

    for token in tokens:
        if not token:
            continue
        if len(token) > max_chars:
            # Flush what we have so far before diving deeper.
            append_current()
            for sentence in _split_sentences(token):
                if len(sentence) > max_chars:
                    # Fallback: hard wrap.
                    for chunk in _chunk_plain(sentence, max_chars):
                        parts.append(chunk)
                    continue
                if len(current) + len(sentence) > max_chars:
                    append_current()
                current += sentence
            append_current()
            continue

        if len(current) + len(token) > max_chars:
            append_current()
        current += token

    append_current()
    return parts


def _split_sentences(text: str) -> Iterable[str]:
    sentences = _SENTENCE_RE.findall(text)
    return [s for s in sentences if s]


def _chunk_plain(text: str, size: int) -> Iterable[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]
