"""Fingerprint fuzzy-match (mục 3.3 tài liệu gốc).

Kết hợp SMBIOS UUID, MachineGuid, serial mainboard → hash có trọng số.
Server fuzzy-match khi enroll: tính điểm tương đồng, quyết định máy cũ/mới.
"""
from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher


def compute_weighted_id(fingerprint: dict[str, str]) -> str:
    """Tạo ID có trọng số từ fingerprint.

    Trọng số: SMBIOS UUID (0.5), MachineGuid (0.3), serial mainboard (0.2).
    Nếu một field null → trọng số dồn cho các field còn lại.
    """
    components = [
        ("uuid", "smbios_uuid", 0.5),
        ("guid", "machine_guid", 0.3),
        ("serial", "mainboard_serial", 0.2),
    ]
    present = [(name, field, w) for name, field, w in components if fingerprint.get(field)]
    if not present:
        return hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()

    # Chuẩn hóa trọng số
    total = sum(w for _, _, w in present)
    norm = [w / total for _, _, w in present]

    # Hash từng thành phần, nhân với trọng số
    parts = []
    for (name, field, _), w in zip(present, norm):
        h = hashlib.sha256(fingerprint[field].encode()).hexdigest()
        parts.append(f"{h[: int(w * 32)]}")
    return hashlib.sha256("".join(parts).encode()).hexdigest()


def similarity_score(fp1: dict[str, str], fp2: dict[str, str]) -> float:
    """Tính điểm tương đồng (0.0–1.0) giữa 2 fingerprint."""
    keys = {"smbios_uuid", "machine_guid", "mainboard_serial"}
    weights = {"smbios_uuid": 0.5, "machine_guid": 0.3, "mainboard_serial": 0.2}
    total = 0.0
    score = 0.0
    for k in keys:
        v1 = fp1.get(k, "")
        v2 = fp2.get(k, "")
        if not v1 or not v2:
            continue
        total += weights[k]
        if v1 == v2:
            score += weights[k]
        else:
            # Fuzzy match xâu
            ratio = SequenceMatcher(None, v1, v2).ratio()
            if ratio > 0.8:
                score += weights[k] * ratio
    if total == 0:
        return 0.0
    return score / total


def is_same_machine(fp1: dict[str, str], fp2: dict[str, str], threshold: float = 0.6) -> bool:
    """Quyết định 2 fingerprint có cùng 1 máy thật không."""
    return similarity_score(fp1, fp2) >= threshold