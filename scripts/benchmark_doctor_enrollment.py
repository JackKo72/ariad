#!/usr/bin/env python3
"""`MANIFEST=cases.json ENROLL_DIR=enroll/ apps/api/.venv/bin/python scripts/benchmark_doctor_enrollment.py`

Scores doctor-voice enrollment (app/eval/doctor_enrollment.py) on top of the
existing sherpa-onnx diarizer: does a pre-recorded doctor voiceprint find the
doctor's clusters, and do small foreign clusters get flagged as
contamination? Opt-in evaluation only -- the product pipeline does not use
voiceprints (docs/PRODUCT.md, docs/AI_PIPELINE.md).

Inputs
  ENROLL_DIR/<doctor_id>/*.wav   clean clips of each doctor speaking alone.
                                 3-5 clips, 10-30 s each, recorded in the
                                 real room with the real microphone.
  MANIFEST (JSON list), paths relative to the manifest file:
    [{"id": "case1", "doctor": "<doctor_id>",
      "audio": "visit.wav", "ref": "visit.transcript.json",
      "contamination": {"audio": "other.wav", "ref": "other.transcript.json",
                        "gain_db": -12, "offset": 5.0}}]   # optional
    `ref` uses the tests/fixtures/audio/*.transcript.json format
    (start/end/speaker/expected_role). Injected contamination turns are
    scored as role "contamination".
  ARIAD_SHERPA_MODELS_DIR  needs only the segmentation model and emb.onnx
                           (Whisper/VAD are not used here).
  THRESHOLD (0.5), MIN_SHARE (0.1), COLLAR (0.25)

Privacy: real doctor clips and visit recordings must stay outside the repo.
Voiceprints live only in memory -- never written to disk. Output is numbers
only, no transcript text.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.eval.diarization_metrics import Turn, compute_der, turns_from_fixture  # noqa: E402
from app.eval.doctor_enrollment import (  # noqa: E402
    ClusterInfo,
    build_voiceprint,
    cluster_majority_roles,
    cosine,
    label_clusters,
    score_enrollment,
    similarity_margin,
)
from compare_diarization_engines import _load_env_local, _load_pcm  # noqa: E402

MIN_TURN_SECONDS = 1.0  # shorter turns give unstable embeddings
ENROLL_WINDOW_SECONDS = 10.0


def _build_extractor(models_dir: str):
    import sherpa_onnx

    from app.providers.sherpa_onnx_asr import _model_paths

    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(_model_paths(models_dir)["embedding"]), num_threads=2, provider="cpu"
    )
    return sherpa_onnx.SpeakerEmbeddingExtractor(config)


def _embed(extractor, samples, sample_rate: int) -> list[float] | None:
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate, samples)
    stream.input_finished()
    if not extractor.is_ready(stream):
        return None
    return list(extractor.compute(stream))


def _enroll(extractor, clips: list[Path]) -> list[float]:
    """Each clip is cut into <=10 s windows; every window's embedding counts."""
    embeddings = []
    for clip in clips:
        frames, sr, _ = _load_pcm(clip)
        step = int(ENROLL_WINDOW_SECONDS * sr)
        for i in range(0, len(frames), step):
            window = frames[i : i + step]
            if len(window) >= 2 * sr and (emb := _embed(extractor, window, sr)) is not None:
                embeddings.append(emb)
    return build_voiceprint(embeddings)


def _mix_contamination(frames, sr: int, spec: dict, base: Path, duration: float):
    """Adds attenuated foreign speech at an offset; returns mixed frames and
    reference turns (role "contamination") clipped to the recording."""
    import numpy as np

    other, _, _ = _load_pcm(base / spec["audio"])
    gain = 10 ** (float(spec.get("gain_db", -12)) / 20)
    offset = float(spec.get("offset", 0.0))
    start = int(offset * sr)
    mixed = frames.copy()
    length = max(0, min(len(other), len(mixed) - start))
    mixed[start : start + length] += gain * other[:length]
    mixed = np.clip(mixed, -1.0, 1.0)
    turns = [
        Turn(t.start + offset, min(t.end + offset, duration), f"contam_{t.speaker}", "contamination")
        for t in turns_from_fixture(json.loads((base / spec["ref"]).read_text()))
        if t.start + offset < duration
    ]
    return mixed, turns


def _run_case(case: dict, base: Path, diarizer, extractor, voiceprints: dict, cfg: dict) -> dict:
    frames, sr, duration = _load_pcm(base / case["audio"])
    reference = turns_from_fixture(json.loads((base / case["ref"]).read_text()))
    if case.get("contamination"):
        frames, contam_turns = _mix_contamination(frames, sr, case["contamination"], base, duration)
        reference = reference + contam_turns

    hyp = [Turn(s.start, s.end, str(s.speaker)) for s in diarizer.process(frames).sort_by_start_time()]

    clusters: dict[str, ClusterInfo] = {}
    for spk in sorted({t.speaker for t in hyp}):
        turns = [t for t in hyp if t.speaker == spk]
        seconds = sum(t.end - t.start for t in turns)
        chunks = [frames[int(t.start * sr) : int(t.end * sr)] for t in turns]
        embs = [e for c, t in zip(chunks, turns) if t.end - t.start >= MIN_TURN_SECONDS and (e := _embed(extractor, c, sr))]
        if not embs:  # only short turns: embed them concatenated
            import numpy as np

            e = _embed(extractor, np.concatenate(chunks), sr)
            embs = [e] if e else []
        if embs:
            clusters[spk] = ClusterInfo(build_voiceprint(embs), seconds)

    doctor_vp = voiceprints[case["doctor"]]
    decisions = label_clusters(clusters, doctor_vp, cfg["threshold"], cfg["min_share"])
    majority = cluster_majority_roles(reference, hyp)
    score = score_enrollment(reference, hyp, decisions, collar=cfg["collar"])
    der = compute_der(reference, hyp, collar=cfg["collar"])

    # Other enrolled doctors must NOT match this doctor's clusters.
    true_doctor = [s for s, r in majority.items() if r == "doctor" and s in clusters]
    impostor = [
        cosine(clusters[s].embedding, vp) for d, vp in voiceprints.items() if d != case["doctor"] for s in true_doctor
    ]

    return {
        "der": der.der,
        "speakers_ref_hyp": [der.ref_speakers, der.hyp_speakers],
        "doctor_recall": score.doctor_recall,
        "doctor_precision": score.doctor_precision,
        "contamination_kept": score.contamination_kept,
        "conversation_dropped": score.conversation_dropped,
        "margin": similarity_margin(decisions, majority),
        "impostor_max_sim": max(impostor) if impostor else None,
        "clusters": [
            {
                "cluster": s,
                "true_role": majority.get(s),
                "label": d.label,
                "similarity": round(d.similarity, 3),
                "share": round(d.share, 3),
            }
            for s, d in decisions.items()
        ],
    }


def _fmt(value, spec=".3f") -> str:
    return "-" if value is None else format(value, spec)


def main() -> int:
    manifest_arg, enroll_arg = os.environ.get("MANIFEST"), os.environ.get("ENROLL_DIR")
    if not manifest_arg or not enroll_arg:
        print(__doc__)
        return 1
    _load_env_local()
    models_dir = os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")
    cfg = {
        "threshold": float(os.environ.get("THRESHOLD", "0.5")),
        "min_share": float(os.environ.get("MIN_SHARE", "0.1")),
        "collar": float(os.environ.get("COLLAR", "0.25")),
    }

    from app.providers.sherpa_onnx_asr import _model_paths, build_diarizer

    needed = [_model_paths(models_dir)[k] for k in ("segmentation", "embedding")]
    if missing := [str(p) for p in needed if not p.exists()]:
        print(f"model file(s) not found: {missing} (see README.md)")
        return 1

    manifest_path = Path(manifest_arg)
    cases = json.loads(manifest_path.read_text())
    extractor = _build_extractor(models_dir)
    diarizer = build_diarizer(models_dir, "cpu")

    voiceprints = {}
    for doctor_dir in sorted(p for p in Path(enroll_arg).iterdir() if p.is_dir()):
        clips = sorted(doctor_dir.glob("*.wav"))
        if clips:
            voiceprints[doctor_dir.name] = _enroll(extractor, clips)
            print(f"enrolled {doctor_dir.name}: {len(clips)} clip(s)")
    print(f"settings: {cfg}\n")

    results = {}
    for case in cases:
        if case["doctor"] not in voiceprints:
            print(f"[{case['id']}] SKIPPED: no enrollment clips for doctor {case['doctor']!r}")
            continue
        results[case["id"]] = r = _run_case(case, manifest_path.parent, diarizer, extractor, voiceprints, cfg)
        print(f"[{case['id']}]")
        for c in r["clusters"]:
            print(f"  cluster {c['cluster']}: true={c['true_role']}, label={c['label']}, sim={c['similarity']}, share={c['share']}")

    header = f"{'case':<26}{'DER':>7}{'spk':>7}{'dr_rec':>8}{'dr_prec':>9}{'contam_kept':>13}{'conv_drop':>11}{'margin':>8}{'impostor':>10}"
    print("\n" + header + "\n" + "-" * len(header))
    for cid, r in results.items():
        spk = "{}/{}".format(*r["speakers_ref_hyp"])
        print(
            f"{cid:<26}{_fmt(r['der']):>7}{spk:>7}{_fmt(r['doctor_recall']):>8}{_fmt(r['doctor_precision']):>9}"
            f"{_fmt(r['contamination_kept']):>13}{_fmt(r['conversation_dropped']):>11}{_fmt(r['margin']):>8}"
            f"{_fmt(r['impostor_max_sim']):>10}"
        )
    print(
        "\ndr_rec/dr_prec: 의사 발화를 의사로 찾은 비율 / 의사로 표시한 것 중 진짜 의사 비율 (높을수록 좋음)\n"
        "contam_kept: 섞어 넣은 오염 발화가 대화로 살아남은 비율 (낮을수록 좋음)\n"
        "conv_drop: 진짜 대화가 오염으로 버려진 비율 (낮을수록 좋음 -- 조용한 보호자 누락 확인)\n"
        "margin: 의사 묶음 최저 유사도 - 나머지 최고 유사도. 양수이고 클수록 THRESHOLD 설정 여유가 큼\n"
        "impostor: 다른 등록 의사 목소리와의 최고 유사도. THRESHOLD보다 충분히 낮아야 함"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
