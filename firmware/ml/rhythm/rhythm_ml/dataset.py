from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .features import (
    STEP_SECONDS,
    WINDOW_SECONDS,
    detect_firmware_beats,
    estimate_sample_rate,
    resample_ppg,
    window_rows,
)


EXPECTED_MD5 = {
    "af": "df323c2be9db41589b5011ac9efb54ca",
    "non_af": "84d5ad5e9fe94e83b40d6dbd36e4210e",
}


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subject_id(member_name: str, group: str) -> str:
    match = re.search(r"_(\d+)_data\.csv$", member_name, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"cannot parse subject id from {member_name}")
    return f"{group.upper()}_{int(match.group(1)):03d}"


def _csv_members(archive: zipfile.ZipFile) -> list[str]:
    return sorted(
        name
        for name in archive.namelist()
        if name.lower().endswith("_data.csv") and not name.startswith("__MACOSX/")
    )


def _process_archive(zip_path: Path, group: str, label: int) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    subjects: list[dict] = []
    with zipfile.ZipFile(zip_path) as archive:
        members = _csv_members(archive)
        if not members:
            raise ValueError(f"no *_data.csv files found in {zip_path}")
        for position, member in enumerate(members, start=1):
            subject = _subject_id(member, group)
            print(f"[{group}] {position}/{len(members)} {subject}", flush=True)
            with archive.open(member) as handle:
                frame = pd.read_csv(
                    handle,
                    usecols=["Time", "PPG"],
                    dtype={"Time": "float64", "PPG": "float64"},
                )
            time = frame["Time"].to_numpy(dtype=np.float64, copy=False)
            ppg = frame["PPG"].to_numpy(dtype=np.float64, copy=False)
            source_hz = estimate_sample_rate(time)
            if not 124.0 <= source_hz <= 126.0:
                raise ValueError(f"{subject}: expected 125 Hz, got {source_hz:.3f} Hz")
            ppg_25 = resample_ppg(ppg, source_hz)
            beats = detect_firmware_beats(ppg_25)
            duration_seconds = float(time[-1] - time[0])
            possible_windows = max(
                0,
                int(np.floor((duration_seconds - WINDOW_SECONDS) / STEP_SECONDS)) + 1,
            )
            subject_rows = window_rows(
                beats=beats,
                duration_seconds=duration_seconds,
                subject_id=subject,
                label=label,
            )
            rows.extend(subject_rows)
            subjects.append(
                {
                    "subject_id": subject,
                    "label": int(label),
                    "group": group,
                    "source_member": member,
                    "source_hz": source_hz,
                    "duration_seconds": duration_seconds,
                    "detected_ibi": int(beats.ibi_ms.size),
                    "usable_windows": len(subject_rows),
                    "possible_windows": possible_windows,
                    "discarded_windows": possible_windows - len(subject_rows),
                    "orientation": int(beats.orientation),
                }
            )
    return rows, subjects


def build_public_features(
    af_zip: Path,
    non_af_zip: Path,
    output_csv: Path,
    manifest_path: Path,
) -> pd.DataFrame:
    af_zip = Path(af_zip).resolve()
    non_af_zip = Path(non_af_zip).resolve()
    for path in (af_zip, non_af_zip):
        if not path.is_file():
            raise FileNotFoundError(path)

    archive_info: list[dict[str, Any]] = []
    for path, group in ((af_zip, "af"), (non_af_zip, "non_af")):
        md5 = file_digest(path, "md5")
        expected = EXPECTED_MD5[group]
        if md5.lower() != expected:
            raise ValueError(
                f"{path.name} MD5 mismatch: expected {expected}, got {md5}"
            )
        archive_info.append(
            {
                "group": group,
                "file_name": path.name,
                "bytes": path.stat().st_size,
                "md5": md5,
                "sha256": file_digest(path, "sha256"),
            }
        )

    af_rows, af_subjects = _process_archive(af_zip, "af", 1)
    normal_rows, normal_subjects = _process_archive(non_af_zip, "non_af", 0)
    frame = pd.DataFrame(af_rows + normal_rows)
    if frame.empty:
        raise ValueError("feature extraction produced no usable windows")
    usable_by_label = frame.groupby("label")["subject_id"].nunique().to_dict()
    if usable_by_label.get(0, 0) < 2 or usable_by_label.get(1, 0) < 2:
        raise ValueError(f"both classes need multiple usable subjects: {usable_by_label}")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_values(["label", "subject_id", "window_end_s"]).to_csv(
        output_csv, index=False
    )
    all_subjects = af_subjects + normal_subjects
    possible_windows = sum(item["possible_windows"] for item in all_subjects)
    discarded_windows = possible_windows - len(frame)
    manifest = {
        "dataset": "MIMIC PERform AF",
        "source": "https://zenodo.org/records/6807403",
        "license": "See LICENSE in each source archive",
        "target_sample_hz": 25,
        "window_seconds": 15,
        "step_seconds": 5,
        "archives": archive_info,
        "subjects": all_subjects,
        "total_windows": int(len(frame)),
        "possible_windows": int(possible_windows),
        "discarded_windows": int(discarded_windows),
        "discarded_window_fraction": (
            float(discarded_windows / possible_windows) if possible_windows else 0.0
        ),
        "usable_subjects_by_label": {
            str(key): int(value) for key, value in usable_by_label.items()
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return frame


def load_or_build_public_features(
    af_zip: Path,
    non_af_zip: Path,
    output_csv: Path,
    manifest_path: Path,
    rebuild: bool = False,
) -> pd.DataFrame:
    if output_csv.is_file() and not rebuild:
        print(f"[cache] loading {output_csv}", flush=True)
        return pd.read_csv(output_csv)
    return build_public_features(af_zip, non_af_zip, output_csv, manifest_path)
