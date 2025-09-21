import asyncio
import inspect
import threading
from pathlib import Path

import pytest

from transfold.cli import Settings, read_and_segment_async, run
from transfold.chunking import SegmentedDocument, Segment, segment_document


class RecordingWriter:
    instances: list["RecordingWriter"] = []

    def __init__(self) -> None:
        self.tasks: list[tuple[Path, str, bool, str]] = []
        RecordingWriter.instances.append(self)

    def start(self) -> None:
        return None

    def submit(self, task: tuple[Path, str, bool, str]) -> None:
        self.tasks.append(task)
        path, content, _, mode = task
        path.parent.mkdir(parents=True, exist_ok=True)
        write_mode = "w" if mode == "replace" else "a"
        with path.open(write_mode, encoding="utf-8", newline="") as handle:
            handle.write(content)

    def close(self) -> None:
        return None


class StubTranslator:
    def __init__(self, *, progress_callback=None, **_: object) -> None:
        from transfold.translator import TranslatorStats

        self.progress_callback = progress_callback
        self.stats = TranslatorStats()

    async def close(self) -> None:
        return None

    async def translate_segments(self, segments, *, segment_callback=None):
        for segment in segments:
            if segment.translate and segment.content.strip():
                self.stats.total_segments += 1
                self.stats.api_calls += 1
                self.stats.batches += 1
                segment.translation = f"[T]{segment.content}"
                if self.progress_callback:
                    self.progress_callback(1)
            else:
                segment.translation = segment.content
            await asyncio.sleep(0)
            if segment_callback is not None:
                result = segment_callback(segment)
                if inspect.isawaitable(result):
                    await result


@pytest.mark.parametrize("stream_writes", [True, False])
def test_run_stream_writes_incremental(stream_writes, monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    document = "First line.\nSecond line that is longer.\nThird line."  # ensures multiple chunks with small max_chars
    source = input_dir / "doc.md"
    source.write_text(document, encoding="utf-8")

    settings = Settings(
        input_dir=input_dir,
        output_dir=output_dir,
        extensions=["md"],
        target_lang="fr",
        source_lang="en",
        model="test-model",
        concurrency=2,
        include=[],
        exclude=[],
        max_chars=12,
        split_threshold=None,
        chunk_strategy="markdown",
        translate_code=False,
        translate_frontmatter=False,
        dry_run=False,
        backup=False,
        stream_writes=stream_writes,
        retry=1,
        timeout=30.0,
        glossary=None,
        api_key="dummy",
        debug=False,
        batch_chars=50,
        batch_segments=1,
    )

    RecordingWriter.instances.clear()
    monkeypatch.setattr("transfold.cli.WriterThread", RecordingWriter)
    monkeypatch.setattr("transfold.cli.OpenRouterTranslator", StubTranslator)

    exit_code = run(settings)
    assert exit_code == 0

    output_file = output_dir / "doc.md"
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")

    # Recreate expected translation using the same segmentation logic.
    segmented = segment_document(document, strategy="markdown", max_chars=12, preserve_code=True, preserve_frontmatter=True)
    for segment in segmented.segments:
        if segment.translate and segment.content.strip():
            segment.translation = f"[T]{segment.content}"
        else:
            segment.translation = segment.content
    expected = segmented.merge()
    assert content == expected

    writer_instance = RecordingWriter.instances[0]
    modes = [task[3] for task in writer_instance.tasks]
    if stream_writes:
        assert modes and modes[0] == "replace"
        assert all(mode in {"replace", "append"} for mode in modes)
        assert modes.count("replace") == 1
    else:
        assert modes == ["replace"]


@pytest.mark.asyncio
async def test_read_and_segment_async_runs_in_thread(tmp_path):
    target = tmp_path / "file.md"
    target.write_text("content", encoding="utf-8")

    called_threads: list[threading.Thread] = []

    def fake_read(path: Path) -> str:
        called_threads.append(threading.current_thread())
        return path.read_text(encoding="utf-8")

    def fake_segment(text: str, **_: object) -> SegmentedDocument:
        segment = Segment(index=0, content=text, translate=True)
        return SegmentedDocument([segment])

    settings = Settings(
        input_dir=tmp_path,
        output_dir=None,
        extensions=["md"],
        target_lang="fr",
        source_lang="en",
        model="model",
        concurrency=1,
        include=[],
        exclude=[],
        max_chars=4000,
        split_threshold=None,
        chunk_strategy="markdown",
        translate_code=False,
        translate_frontmatter=False,
        dry_run=False,
        backup=False,
        stream_writes=False,
        retry=1,
        timeout=60.0,
        glossary=None,
        api_key="dummy",
        debug=False,
        batch_chars=16000,
        batch_segments=6,
    )

    text, segmented, translatable = await read_and_segment_async(
        target,
        settings=settings,
        read_text_fn=fake_read,
        segment_document_fn=fake_segment,
    )

    assert text == "content"
    assert isinstance(segmented, SegmentedDocument)
    assert translatable == 1
    assert called_threads, "fake_read should have been invoked"
    assert called_threads[0] is not threading.main_thread()
