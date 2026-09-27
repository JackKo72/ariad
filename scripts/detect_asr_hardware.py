#!/usr/bin/env python3
"""`apps/api/.venv/bin/python scripts/detect_asr_hardware.py`

tasks/05_ASR_HARDWARE_SPEEDUP.md item 1: reports the hardware/software facts
a fair ASR speed comparison needs -- CPU model/physical cores/RAM, GPU
vendor/model/VRAM/driver (or "no GPU detected" and why), which onnxruntime
execution providers sherpa-onnx structurally supports vs. what this
specific installed build can actually construct, whether faster-whisper/
ctranslate2 are installed, model file quantization (from file names/sizes),
and the num_threads sherpa_onnx_asr.py would resolve to.

Deliberately does NOT run any real ASR -- this only checks capability and
configuration, in seconds, without needing model weights or audio. Whether
a capability that "constructs" (e.g. provider="cuda") actually accelerates
anything (vs. silently no-op'ing or erroring at first real decode) is a
separate question scripts/compare_asr_engines.py answers by actually
running audio through it and sampling GPU/CPU utilization concurrently --
"GPU 사용 가능 표시만으로 충분하다고 판단하지 마" (tasks/05 item 1).

No audio, transcript, or patient content is read or printed by this script
-- it only inspects hardware/software configuration. Free, opt-in, never
part of `make test`/`make e2e`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0, (result.stdout or result.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _cpu_info() -> dict:
    model_name = None
    physical_ids: set[tuple[str, str]] = set()
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        current_physical, current_core = None, None
        for line in cpuinfo.splitlines():
            if line.startswith("model name") and model_name is None:
                model_name = line.split(":", 1)[1].strip()
            elif line.startswith("physical id"):
                current_physical = line.split(":", 1)[1].strip()
            elif line.startswith("core id"):
                current_core = line.split(":", 1)[1].strip()
                if current_physical is not None:
                    physical_ids.add((current_physical, current_core))
    except FileNotFoundError:
        pass

    mem_total_kb = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_total_kb = int(line.split()[1])
                break
    except FileNotFoundError:
        pass

    return {
        "model_name": model_name or "(확인 불가, /proc/cpuinfo 없음)",
        "logical_cpus": os.cpu_count(),
        "physical_cores": len(physical_ids) or None,
        "ram_gb": round(mem_total_kb / 1024 / 1024, 1) if mem_total_kb else None,
    }


def _nvidia_gpu_info() -> list[dict] | None:
    ok, out = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if not ok:
        return None
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            gpus.append({"name": parts[0], "vram_mb": parts[1], "driver_version": parts[2]})
    return gpus or None


def _amd_gpu_info() -> list[dict] | None:
    ok, out = _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram"])
    if not ok:
        return None
    return [{"raw_rocm_smi_output": out}]


def _generic_gpu_via_lspci() -> list[str] | None:
    ok, out = _run(["lspci"])
    if not ok:
        return None
    lines = [line for line in out.splitlines() if any(k in line for k in ("VGA", "3D controller", "Display"))]
    return lines or None


def _gpu_info() -> dict:
    nvidia = _nvidia_gpu_info()
    if nvidia:
        return {"vendor": "nvidia", "gpus": nvidia}
    amd = _amd_gpu_info()
    if amd:
        return {"vendor": "amd", "gpus": amd}
    generic = _generic_gpu_via_lspci()
    if generic:
        return {"vendor": "unknown (lspci found a display device but no vendor tool responded)", "gpus": generic}
    return {"vendor": None, "gpus": None, "note": "no GPU detected (no nvidia-smi/rocm-smi, lspci found nothing)"}


def _sherpa_onnx_provider_support() -> dict:
    try:
        import sherpa_onnx
    except ImportError:
        return {"installed": False}

    result: dict = {"installed": True, "version": getattr(sherpa_onnx, "__version__", "unknown")}
    # from_whisper()/from_sense_voice() both document provider in {cpu, cuda, coreml} --
    # this only confirms the Python API accepts the string, not that the
    # underlying onnxruntime build actually has the CUDA execution provider
    # compiled in (that only surfaces as an error/fallback at real model load).
    result["from_whisper_supports_provider_kwarg"] = "provider" in sherpa_onnx.OfflineRecognizer.from_whisper.__doc__ if sherpa_onnx.OfflineRecognizer.from_whisper.__doc__ else "unknown"
    result["has_from_sense_voice"] = hasattr(sherpa_onnx.OfflineRecognizer, "from_sense_voice")
    try:
        vad_cfg = sherpa_onnx.VadModelConfig()
        result["vad_config_has_provider_attr"] = hasattr(vad_cfg, "provider")
    except Exception as exc:  # pragma: no cover - defensive, environment-dependent
        result["vad_config_check_error"] = type(exc).__name__
    return result


def _faster_whisper_status() -> dict:
    try:
        import faster_whisper  # noqa: F401

        return {"installed": True}
    except ImportError:
        return {
            "installed": False,
            "install_hint": "apps/api/.venv/bin/pip install faster-whisper (pulls in ctranslate2)",
        }


def _model_quantization_info(models_dir: str) -> dict:
    root = Path(models_dir)
    if not root.exists():
        return {"models_dir": models_dir, "exists": False}
    files = []
    for path in root.rglob("*.onnx"):
        size_mb = path.stat().st_size / 1024 / 1024
        files.append(
            {
                "path": str(path.relative_to(root)),
                "size_mb": round(size_mb, 1),
                "looks_int8_quantized": "int8" in path.name.lower(),
            }
        )
    return {"models_dir": models_dir, "exists": True, "onnx_files": files}


def _num_threads_resolution() -> dict:
    env_value = os.environ.get("ARIAD_SHERPA_NUM_THREADS")
    resolved = int(env_value) if env_value else (os.cpu_count() or 2)
    return {"ARIAD_SHERPA_NUM_THREADS_env": env_value, "resolved_num_threads": resolved}


def main() -> int:
    report = {
        "cpu": _cpu_info(),
        "gpu": _gpu_info(),
        "sherpa_onnx": _sherpa_onnx_provider_support(),
        "faster_whisper": _faster_whisper_status(),
        "num_threads": _num_threads_resolution(),
        "model_files": _model_quantization_info(os.environ.get("ARIAD_SHERPA_MODELS_DIR", "./models")),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    print("\n요약:")
    gpu = report["gpu"]
    if gpu["vendor"] in (None,) or gpu.get("gpus") is None:
        print("- GPU 없음 (또는 감지 실패) -- CPU 후보만 비교 가능. GPU가 실제로 있다면")
        print("  드라이버(nvidia-smi/rocm-smi)가 PATH에 있는지, 컨테이너/가상화 환경이라면")
        print("  GPU passthrough가 되어 있는지 확인 필요.")
    else:
        print(f"- GPU 감지됨: vendor={gpu['vendor']}, {gpu['gpus']}")
        print("  (감지 == 사용 가능은 아님 -- scripts/compare_asr_engines.py로 실제 가속 확인 필요)")
    if not report["sherpa_onnx"].get("installed"):
        print("- sherpa_onnx가 설치되어 있지 않음 (ARIAD_MODE=provider 미설정 환경일 수 있음)")
    if not report["faster_whisper"]["installed"]:
        print("- faster-whisper 미설치 -- 후보로 시험하려면:", report["faster_whisper"]["install_hint"])
    if not report["model_files"]["exists"]:
        print(f"- 모델 디렉터리 없음: {report['model_files']['models_dir']} -- README 모델 다운로드 안내 참고")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
