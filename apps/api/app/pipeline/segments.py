"""Segments handed to structure_encounter (docs/stage1_output.md section 6, option C).

The structure LLM used to see only the flattened "의사: ..." transcript, so
any segment ID it emitted was invented. These pure functions build the
segment list it now also receives, keeping each segment's ID, speaker label
and role:

- audio path: the PipelineRun's real segments (seg_001.., speaker A/B/C,
  clinician-confirmed role)
- manual text path: one segment per non-empty line, IDs in the same
  seg_001 format, role read from the line's "의사:"/"환자:"/"보호자:" prefix
"""

from __future__ import annotations

from app.domain.models import PipelineRun

ROLE_LABELS_KO = {
    "doctor": "의사",
    "patient": "환자",
    "guardian": "보호자",
    "unknown": "화자",
}
_LABEL_TO_ROLE = {label: role for role, label in ROLE_LABELS_KO.items()}

Segment = dict[str, str]  # keys: id, speaker, role, text


def segment_id(index: int) -> str:
    """0-based index -> "seg_001" (same format the ASR providers use)."""
    return f"seg_{index + 1:03d}"


def segments_from_transcript_text(transcript_text: str) -> list[Segment]:
    segments: list[Segment] = []
    lines = [line.strip() for line in transcript_text.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        label, sep, rest = line.partition(":")
        label = label.strip()
        if sep and label in _LABEL_TO_ROLE:
            speaker, role, text = label, _LABEL_TO_ROLE[label], rest.strip()
        else:
            speaker, role, text = "", "unknown", line
        segments.append({"id": segment_id(i), "speaker": speaker, "role": role, "text": text})
    return segments


def segments_from_pipeline_run(run: PipelineRun) -> list[Segment]:
    return [
        {
            "id": seg.id,
            "speaker": seg.speaker,
            # Same fallback as routes/encounters.py:_derive_transcript_text, so
            # the segment tag always agrees with the transcript line label.
            "role": run.roles.get(seg.speaker, "unknown"),
            "text": seg.text,
        }
        for seg in sorted(run.segments, key=lambda s: s.start)
    ]
