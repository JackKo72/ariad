#!/usr/bin/env python3
"""`python3 scripts/generate_noisy_diarization_set.py` (or `make noisy-diarization-set`)

tasks/07_NOISY_DIARIZATION_EVAL.md: builds a diarization eval set with KNOWN
ground truth by mixing a clean synthetic encounter with the interference
ARIAD actually meets on outpatient visits and ward rounds:

  music         -- next room's music (synthetic tonal, non-stationary)
  construction  -- hammer impacts + intermittent drill (synthetic)
  neighbour     -- another bed's rounds: a *second* synthetic conversation,
                   pitch-shifted so it is not the same TTS voice, mixed
                   quieter than ours (SNR > 0 = our encounter is louder).
                   Its turns go into the reference as background speakers,
                   so scripts/eval_diarization_der.py can measure whether
                   they leak into our doctor's/patient's labels.

each at SNR 0/5/10 dB (SNRS=...), plus the clean baseline. SNR is measured
over speech-active samples only (app/eval/noise_mix.py).

Inputs (all synthetic -- CLAUDE.md forbids real patient audio here):
  CLEAN / CLEAN_GT              default tests/fixtures/audio/sample_consultation.{wav,transcript.json}
  INTERFERER / INTERFERER_GT    default tests/fixtures/audio/vital_signs_dictation.{wav,transcript.json}
  NOISE_MUSIC, NOISE_CONSTRUCTION  optional: a real noise recording (no
                                   speech from real patients) to use instead
                                   of the synthetic generator, e.g. a CC0
                                   clip -- synthetic music has no vocals,
                                   which real radio music often does.
  OUT_DIR   default data/eval_noisy_diarization (gitignored -- never commit)
  SNRS      default 0,5,10        SEED  default 7

Outputs per condition: <name>.wav, <name>.ref.json, <name>.rttm, plus
manifest.json listing them for scripts/eval_diarization_der.py.

Known limitation: the default fixtures' two speakers are the same espeak-ng
voice at different pitches (README "알려진 제한"), so absolute DER here is
pessimistic for real voices -- compare engines/settings against each other
on the same set, don't read the number as a real-clinic DER.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.eval.noise_mix import fit_length, mix_at_snr  # noqa: E402

SAMPLE_RATE = 16000
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "audio"
# asetrate pitch+tempo shift for the neighbour conversation: 1.12 is about
# two semitones up -- enough that it is not literally the foreground voice.
INTERFERER_PITCH_FACTOR = 1.12
INTERFERER_OFFSET_SECONDS = 2.0


def load_audio(path: Path, pitch_factor: float = 1.0) -> np.ndarray:
    """Any ffmpeg-readable file -> mono 16 kHz float32 in [-1, 1]."""
    filters = f"asetrate={int(SAMPLE_RATE * pitch_factor)},aresample={SAMPLE_RATE}"
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE)]
    if pitch_factor != 1.0:
        command += ["-af", filters]
    command += ["-f", "f32le", "-"]
    raw = subprocess.run(command, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def load_segments(path: Path, prefix: str = "", time_scale: float = 1.0, offset: float = 0.0,
                  background: bool = False) -> list[dict]:
    """Ground-truth turns from a fixture transcript JSON -- speaker/time only,
    the text is deliberately dropped (a diarization reference needs none)."""
    segments = json.loads(path.read_text(encoding="utf-8"))["segments"]
    return [
        {
            "start": round(offset + seg["start"] * time_scale, 3),
            "end": round(offset + seg["end"] * time_scale, 3),
            "speaker": f"{prefix}{seg['speaker']}",
            "background": background,
        }
        for seg in segments
    ]


def speech_mask(segments: list[dict], n_samples: int) -> np.ndarray:
    mask = np.zeros(n_samples, dtype=bool)
    for seg in segments:
        mask[int(seg["start"] * SAMPLE_RATE):int(seg["end"] * SAMPLE_RATE)] = True
    return mask


def synth_music(n_samples: int, rng: np.random.Generator) -> np.ndarray:
    """Chord-per-beat pad + bass + vibrato melody: tonal and rhythmic, i.e.
    exactly what afftdn's stationary-noise model can't learn away."""
    t = np.arange(n_samples) / SAMPLE_RATE
    beat = 60 / 100  # 100 bpm
    chords = [(220.0, 277.2, 329.6), (196.0, 246.9, 293.7), (174.6, 220.0, 261.6), (196.0, 246.9, 311.1)]
    out = np.zeros(n_samples)
    for i in range(int(np.ceil(t[-1] / beat)) + 1):
        lo, hi = int(i * beat * SAMPLE_RATE), min(n_samples, int((i + 1) * beat * SAMPLE_RATE))
        if lo >= n_samples:
            break
        tt = t[lo:hi] - t[lo]
        envelope = np.exp(-3.0 * tt)
        chord = chords[(i // 4) % len(chords)]
        for f in chord:
            for harmonic, amp in ((1, 1.0), (2, 0.4), (3, 0.15)):
                out[lo:hi] += 0.2 * amp * envelope * np.sin(2 * np.pi * f * harmonic * tt)
        out[lo:hi] += 0.5 * envelope * np.sin(2 * np.pi * chord[0] / 2 * tt)
        melody = chord[rng.integers(0, 3)] * 2
        out[lo:hi] += 0.25 * np.sin(2 * np.pi * melody * tt + 0.3 * np.sin(2 * np.pi * 5 * tt))
    return out


def synth_construction(n_samples: int, rng: np.random.Generator) -> np.ndarray:
    """Irregular hammer impacts (noise burst + metallic ring) and an
    intermittent 40 Hz-modulated band-noise drill."""
    out = np.zeros(n_samples)
    pos = 0
    while pos < n_samples:
        length = min(int(0.25 * SAMPLE_RATE), n_samples - pos)
        tt = np.arange(length) / SAMPLE_RATE
        ring = np.sin(2 * np.pi * rng.uniform(800, 2000) * tt)
        out[pos:pos + length] += (rng.standard_normal(length) * np.exp(-tt / 0.01) + 0.5 * ring * np.exp(-tt / 0.06))
        pos += int(rng.uniform(0.3, 1.2) * SAMPLE_RATE)

    pos = int(rng.uniform(0, 3) * SAMPLE_RATE)
    while pos < n_samples:
        length = min(int(rng.uniform(2, 5) * SAMPLE_RATE), n_samples - pos)
        tt = np.arange(length) / SAMPLE_RATE
        band = np.diff(rng.standard_normal(length + 1))  # crude high-pass -> harsher drill tone
        out[pos:pos + length] += 0.4 * band * (0.6 + 0.4 * np.sin(2 * np.pi * 40 * tt))
        pos += length + int(rng.uniform(3, 8) * SAMPLE_RATE)
    return out


def build_neighbour(n_samples: int, interferer_path: Path, interferer_gt: Path) -> tuple[np.ndarray, list[dict]]:
    """Places the pitch-shifted second conversation at a fixed offset (never
    looped -- a looped conversation would need duplicated reference turns),
    truncated to the clean encounter's length."""
    voice = load_audio(interferer_path, INTERFERER_PITCH_FACTOR)
    offset = int(INTERFERER_OFFSET_SECONDS * SAMPLE_RATE)
    track = np.zeros(n_samples, dtype=np.float32)
    usable = max(0, min(len(voice), n_samples - offset))
    track[offset:offset + usable] = voice[:usable]

    duration = n_samples / SAMPLE_RATE
    segments = []
    for seg in load_segments(interferer_gt, prefix="BG_", time_scale=1 / INTERFERER_PITCH_FACTOR,
                             offset=INTERFERER_OFFSET_SECONDS, background=True):
        if seg["start"] < duration:
            segments.append({**seg, "end": round(min(seg["end"], duration), 3)})
    return track, segments


def write_condition(out_dir: Path, name: str, audio: np.ndarray, segments: list[dict]) -> dict:
    write_wav(out_dir / f"{name}.wav", audio)
    (out_dir / f"{name}.ref.json").write_text(json.dumps({"segments": segments}, indent=2), encoding="utf-8")
    rttm = [
        f"SPEAKER {name} 1 {s['start']:.3f} {s['end'] - s['start']:.3f} <NA> <NA> {s['speaker']} <NA> <NA>"
        for s in segments
    ]
    (out_dir / f"{name}.rttm").write_text("\n".join(rttm) + "\n", encoding="utf-8")
    return {"name": name, "wav": f"{name}.wav", "ref": f"{name}.ref.json"}


def main() -> int:
    clean_path = Path(os.environ.get("CLEAN", FIXTURES / "sample_consultation.wav"))
    clean_gt = Path(os.environ.get("CLEAN_GT", clean_path.with_suffix(".transcript.json")))
    interferer_path = Path(os.environ.get("INTERFERER", FIXTURES / "vital_signs_dictation.wav"))
    interferer_gt = Path(os.environ.get("INTERFERER_GT", interferer_path.with_suffix(".transcript.json")))
    out_dir = Path(os.environ.get("OUT_DIR", REPO_ROOT / "data" / "eval_noisy_diarization"))
    snrs = [float(s) for s in os.environ.get("SNRS", "0,5,10").split(",")]
    rng = np.random.default_rng(int(os.environ.get("SEED", "7")))

    for path in (clean_path, clean_gt, interferer_path, interferer_gt):
        if not path.exists():
            print(f"File not found: {path}")
            return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = load_audio(clean_path)
    n = len(clean)
    foreground = load_segments(clean_gt)
    clean_mask = speech_mask(foreground, n)

    noises: dict[str, tuple[np.ndarray, np.ndarray | None, list[dict]]] = {}
    for kind, synth in (("music", synth_music), ("construction", synth_construction)):
        override = os.environ.get(f"NOISE_{kind.upper()}")
        signal = fit_length(load_audio(Path(override)), n) if override else synth(n, rng)
        noises[kind] = (signal, None, [])
    neighbour, neighbour_segments = build_neighbour(n, interferer_path, interferer_gt)
    noises["neighbour"] = (neighbour, speech_mask(neighbour_segments, n), neighbour_segments)

    manifest = [{**write_condition(out_dir, "clean", clean, foreground), "noise": "none", "snr_db": None}]
    for kind, (signal, mask, extra_segments) in noises.items():
        for snr in snrs:
            name = f"{kind}_snr{snr:g}"
            mixed = mix_at_snr(clean, signal, snr, clean_mask=clean_mask, interference_mask=mask)
            entry = write_condition(out_dir, name, mixed, foreground + extra_segments)
            manifest.append({**entry, "noise": kind, "snr_db": snr})

    (out_dir / "manifest.json").write_text(
        json.dumps({"source": clean_path.name, "conditions": manifest}, indent=2), encoding="utf-8"
    )
    print(f"{len(manifest)} conditions ({n / SAMPLE_RATE:.1f}s each) -> {out_dir}")
    for entry in manifest:
        print(f"  {entry['name']}")
    print(f"\nNext: SET_DIR={out_dir} make eval-diarization-der")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
