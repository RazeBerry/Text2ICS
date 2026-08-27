"""Resource-ownership tests for attachment snapshots."""

from pathlib import Path

from eventcalendar.core.attachments import AttachmentStore, ImageAttachmentPayload


def _payload(path: Path, source: str) -> ImageAttachmentPayload:
    path.write_bytes(b"image")
    return ImageAttachmentPayload(source_path=source, mime_type="image/png", temp_path=str(path))


def test_store_owns_accepted_files_and_disposes_rejected_files(tmp_path: Path) -> None:
    store = AttachmentStore(limit=1)
    accepted = _payload(tmp_path / "accepted.png", "source-a")
    over_limit = _payload(tmp_path / "rejected.png", "source-b")

    assert store.add([accepted, over_limit]) == [accepted]
    assert Path(accepted.temp_path).exists()
    assert not Path(over_limit.temp_path).exists()
    assert list(store.payloads) == [accepted]

    store.clear()

    assert not Path(accepted.temp_path).exists()
    assert list(store.payloads) == []


def test_store_rejects_duplicate_source_and_cleans_candidate(tmp_path: Path) -> None:
    store = AttachmentStore(limit=2)
    first = _payload(tmp_path / "first.png", "same-source")
    duplicate = _payload(tmp_path / "duplicate.png", "same-source")

    assert store.add([first]) == [first]
    assert store.add([duplicate]) == []
    assert not Path(duplicate.temp_path).exists()

    store.clear()


def test_resubmitting_same_payload_does_not_delete_owned_file(tmp_path: Path) -> None:
    store = AttachmentStore(limit=2)
    payload = _payload(tmp_path / "same.png", "same-source")

    assert store.add([payload, payload]) == [payload]
    assert Path(payload.temp_path).exists()

    store.clear()
    assert not Path(payload.temp_path).exists()
