"""Unit tests — fingerprint weighted id + fuzzy match."""
from __future__ import annotations

from app.services.fingerprint import (
    compute_weighted_id,
    is_same_machine,
    similarity_score,
)

FP_A = {
    "smbios_uuid": "7C4A-9B21-0000-1111",
    "machine_guid": "abcd-1234-efgh",
    "mainboard_serial": "SN123456789",
}


def test_weighted_id_stable():
    assert compute_weighted_id(FP_A) == compute_weighted_id(dict(FP_A))


def test_weighted_id_differs_when_changed():
    fp_b = dict(FP_A)
    fp_b["mainboard_serial"] = "SN999999999"
    # Thay serial mainboard → id có trọng số nên thay đổi
    assert compute_weighted_id(FP_A) != compute_weighted_id(fp_b)


def test_similarity_same_machine():
    fp_close = dict(FP_A)
    fp_close["mainboard_serial"] = "SN123456789"  # giống hệt
    assert is_same_machine(FP_A, fp_close)


def test_similarity_different_machine():
    fp_diff = {
        "smbios_uuid": "ZZZZ-ZZZZ",
        "machine_guid": "xxxx-yyyy",
        "mainboard_serial": "SN999",
    }
    assert not is_same_machine(FP_A, fp_diff)


def test_similarity_scoring():
    assert 0.0 <= similarity_score(FP_A, dict(FP_A)) <= 1.0
    assert similarity_score(FP_A, dict(FP_A)) == 1.0
    assert similarity_score({}, {}) == 0.0
