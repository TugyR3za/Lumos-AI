from app.retrieval.chunker import chunk_text


def test_chunk_text_preserves_content_and_bounds_size():
    text = "First paragraph.\n\n" + ("second " * 100) + "\n\nLast paragraph."
    chunks = chunk_text(text, target_size=180, overlap=20)

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)
    assert all(len(chunk) <= 220 for chunk in chunks)
    assert "First paragraph." in chunks[0]
    assert "Last paragraph." in chunks[-1]
