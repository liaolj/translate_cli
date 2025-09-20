from transfold.chunking import segment_document


def test_segment_document_avoids_split_below_threshold():
    paragraphs = [" ".join(["alpha"] * 40), " ".join(["beta"] * 40)]
    text = "\n\n".join(paragraphs)
    threshold = len(text) + 10
    max_chars = max(1, len(text) // 2)

    document = segment_document(
        text,
        max_chars=max_chars,
        split_threshold=threshold,
    )

    translatable = [seg for seg in document.segments if seg.translate]
    assert len(translatable) == 1
    assert translatable[0].content == text

def test_segment_document_splits_above_threshold():
    paragraphs = [" ".join([f"para{i}"] * 80) for i in range(5)]
    text = "\n\n".join(paragraphs)
    threshold = len(text) - 10
    max_chars = max(1, len(text) // 3)

    document = segment_document(
        text,
        max_chars=max_chars,
        split_threshold=threshold,
    )

    translatable = [seg for seg in document.segments if seg.translate]
    assert len(translatable) > 1
    for segment in translatable:
        assert len(segment.content) <= max_chars
