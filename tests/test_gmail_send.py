"""Draft parsing must keep video attachments (and the usual documents)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import gmail_send as G  # noqa: E402


def test_draft_parses_video_and_document_attachments(tmp_path):
    p = tmp_path / "draft.txt"
    p.write_text(
        "To: david@example.com\nCc:\nSubject: Re: hello\n"
        "Attachment: documents/assets/demo.mp4, documents/applications/cv.pdf\n"
        "Company: Redpine\nRole: Senior Knowledge Graph Engineer\n---\nBody text\n",
        encoding="utf-8")
    meta, body, att = G._parse_draft(str(p))
    assert meta["to"] == "david@example.com"
    assert body == "Body text"
    assert att == ["documents/assets/demo.mp4", "documents/applications/cv.pdf"]
