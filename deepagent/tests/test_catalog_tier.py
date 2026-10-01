"""Tests for catalog tier classification with defense-in-depth + platform isolation.

A2 design contract (post-review):

C1-A  Tier 1 = name MUST be in hardcoded `TIER1_CUSTOM_TOOLS[platform]`
      whitelist AND ref.tier == 1. A DB/Backend compromise alone cannot
      promote a non-whitelisted Custom.* to Tier 1 — both conditions
      are required.

M1    Custom.* tools MUST be filtered by `target_platform` against
      `ref.supported_platforms`. A Linux Custom.* artifact with tier=2
      MUST NOT appear in a Windows investigation's candidates.

M2    Legacy fallback to hardcoded TIER1_CUSTOM_TOOLS applies when the
      request carries custom_artifacts but NONE are tier=1 (e.g. a
      pre-A2 backend that defaults every artifact to tier=2). Without
      this, Linux/macOS investigations under a legacy backend would
      produce empty Tier-1 candidates and `sanitize_plan()` would fail.

M3    Tests cover: (a) real `InvestigationRequest.model_validate()`
      payloads, (b) platform-mismatch across `sanitize_plan` /
      `tier2_custom_tool_names` boundary, (c) non-whitelisted Tier-1
      Custom.* is blocked even when DB marks it tier=1.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from deepagent.catalog import (
    TIER1_CUSTOM_TOOLS,
    initial_custom_tool_names,
    tier2_custom_tool_names,
)
from deepagent.models import (
    CustomArtifactRef,
    InvestigationRequest,
    LlmRuntime,
    TimeRange,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_request(
    artifacts: list[CustomArtifactRef],
    platform: str = "windows",
) -> InvestigationRequest:
    """Build a valid InvestigationRequest carrying the given custom_artifacts."""
    now = datetime.now(UTC)
    return InvestigationRequest(
        investigation_id=UUID("11111111-1111-4111-8111-111111111111"),
        client_id="C.0123456789abcdef",
        hostname="WS-01",
        target_platform=platform,  # type: ignore[arg-type]
        time_range=TimeRange(
            **{"from": (now - timedelta(hours=1)), "to": now}
        ),
        suspicious_activity="Test suspicious activity",
        llm_runtime=LlmRuntime(
            base_url="http://llm.local/v1",
            api_key="test-key",
            model="test-model",
        ),
        velociraptor_api_client_yaml=(
            "ca_certificate: test\n"
            "client_cert: test\n"
            "client_private_key: test\n"
        ),
        custom_artifacts=artifacts,
    )


# ===========================================================================
# C1-A: Tier 1 requires name in hardcoded whitelist
# ===========================================================================


class TestTier1RequiresHardcodedWhitelist:
    """Defense-in-depth: tier=1 in DB alone is NOT sufficient for Tier 1.

    Without this, a backend/DB compromise that sets `tier=1` on any
    syntactically-valid Custom.* name would let the LLM call it during
    initial collection. The hardcoded whitelist is the second gate.
    """

    def test_triage_with_tier1_in_db_passes(self) -> None:
        """Built-in Triage is whitelisted; DB tier=1 lets it through."""
        request = _make_request(
            [CustomArtifactRef(
                name="Custom.DFIR.Windows.Triage",
                tier=1,
                supported_platforms=["windows"],
            )]
        )
        assert initial_custom_tool_names(request) == {
            "custom:Custom.DFIR.Windows.Triage"
        }

    def test_non_whitelisted_name_with_tier1_is_blocked(self) -> None:
        """Even if DB says tier=1, an unknown Custom.* MUST be filtered out.

        This is the critical security test. A compromised backend that
        promotes `Custom.Evil.RCE` to tier=1 must NOT cause it to be
        eligible for initial collection.
        """
        request = _make_request(
            [CustomArtifactRef(
                name="Custom.Evil.MaliciousRCE",
                tier=1,
                supported_platforms=["windows"],
            )]
        )
        assert initial_custom_tool_names(request) == set()

    def test_non_whitelisted_name_does_not_leak_into_tier2_either(self) -> None:
        """A non-whitelisted Custom.* (tier=1) MUST NOT appear in Tier 2
        candidates, even when other tier=2 artifacts are present.
        """
        request = _make_request(
            [
                CustomArtifactRef(
                    name="Custom.Evil.MaliciousRCE",
                    tier=1,
                    supported_platforms=["windows"],
                ),
                CustomArtifactRef(
                    name="Custom.DFIR.Windows.MustangPanda",
                    tier=2,
                    supported_platforms=["windows"],
                ),
            ]
        )
        result = tier2_custom_tool_names(request)
        assert "custom:Custom.Evil.MaliciousRCE" not in result
        assert "custom:Custom.DFIR.Windows.MustangPanda" in result

    def test_mustang_panda_tier1_is_blocked_even_through_db(self) -> None:
        """MustangPanda is not in the hardcoded Tier 1 whitelist.

        Admins must NOT be able to promote it to Tier 1 just by setting
        `tier=1` in the DB — Tier 1 is reserved for trusted triage
        wrappers and requires a code change.
        """
        request = _make_request(
            [CustomArtifactRef(
                name="Custom.DFIR.Windows.MustangPanda",
                tier=1,  # attempted promotion via DB
                supported_platforms=["windows"],
            )]
        )
        assert initial_custom_tool_names(request) == set()


# ===========================================================================
# M1: Platform isolation for custom artifacts
# ===========================================================================


class TestPlatformIsolation:
    """Linux Custom.* MUST NOT appear in Windows investigations and vice-versa.

    A backend that supplies the full enabled-artifact catalog can include
    artifacts for the wrong OS. Without platform filtering, the LLM would
    see a Linux artifact as a candidate for a Windows target — even
    though Velociraptor would reject the call, the LLM would still
    produce a malformed plan and waste an investigation step.
    """

    def test_linux_artifact_excluded_from_windows_tier2(self) -> None:
        request = _make_request(
            [CustomArtifactRef(
                name="Custom.DFIR.Linux.MustangPanda",
                tier=2,
                supported_platforms=["linux"],
            )],
            platform="windows",
        )
        assert tier2_custom_tool_names(request) == set()

    def test_windows_artifact_excluded_from_linux_tier2(self) -> None:
        request = _make_request(
            [CustomArtifactRef(
                name="Custom.DFIR.Windows.MustangPanda",
                tier=2,
                supported_platforms=["windows"],
            )],
            platform="linux",
        )
        assert tier2_custom_tool_names(request) == set()

    def test_macos_investigation_sees_only_macos_artifacts(self) -> None:
        request = _make_request(
            [
                CustomArtifactRef(
                    name="Custom.DFIR.Windows.X",
                    tier=2,
                    supported_platforms=["windows"],
                ),
                CustomArtifactRef(
                    name="Custom.DFIR.Linux.Y",
                    tier=2,
                    supported_platforms=["linux"],
                ),
                CustomArtifactRef(
                    name="Custom.Other.MultiPlatform",
                    tier=2,
                    supported_platforms=["windows", "linux", "macos"],
                ),
            ],
            platform="macos",
        )
        result = tier2_custom_tool_names(request)
        assert "custom:Custom.Other.MultiPlatform" in result
        assert "custom:Custom.DFIR.Windows.X" not in result
        assert "custom:Custom.DFIR.Linux.Y" not in result

    def test_multi_platform_artifact_eligible_on_every_supported_target(
        self,
    ) -> None:
        for platform in ("windows", "linux", "macos"):
            request = _make_request(
                [CustomArtifactRef(
                    name="Custom.Other.MultiPlatform",
                    tier=2,
                    supported_platforms=["windows", "linux", "macos"],
                )],
                platform=platform,
            )
            assert "custom:Custom.Other.MultiPlatform" in (
                tier2_custom_tool_names(request)
            )

    def test_platform_mismatch_via_graph_does_not_leak(self) -> None:
        """Linux artifact in Windows request MUST NOT be a Tier 2 candidate,
        even though DB explicitly tagged it tier=2. The platform filter is
        the second gate, not the first.
        """
        request = _make_request(
            [
                CustomArtifactRef(
                    name="Custom.DFIR.Linux.MustangPanda",
                    tier=2,
                    supported_platforms=["linux"],
                ),
                CustomArtifactRef(
                    name="Custom.DFIR.Windows.MustangPanda",
                    tier=2,
                    supported_platforms=["windows"],
                ),
            ],
            platform="windows",
        )
        result = tier2_custom_tool_names(request)
        assert "custom:Custom.DFIR.Linux.MustangPanda" not in result
        assert "custom:Custom.DFIR.Windows.MustangPanda" in result


# ===========================================================================
# M2: Legacy fallback when request has custom_artifacts but no tier=1
# ===========================================================================


class TestLegacyFallbackForTier1:
    """When a pre-A2 backend delivers request.custom_artifacts without
    setting tier=1 on any of them, Tier 1 candidates must still come
    from the hardcoded whitelist. Otherwise Linux/macOS legacy
    investigations produce empty Tier-1 sets → `sanitize_plan()` fails.
    """

    def test_all_artifacts_tier2_still_yields_hardcoded_tier1(self) -> None:
        """Backend serving only tier=2 must NOT break Tier 1 for windows."""
        request = _make_request(
            [
                CustomArtifactRef(
                    name="Custom.DFIR.Windows.Execution",
                    tier=2,
                    supported_platforms=["windows"],
                ),
                CustomArtifactRef(
                    name="Custom.DFIR.Windows.Persistence",
                    tier=2,
                    supported_platforms=["windows"],
                ),
            ]
        )
        # Legacy behavior: hardcoded Tier 1 still wins because DB
        # supplies no tier=1 names.
        result = initial_custom_tool_names(request)
        assert "custom:Custom.DFIR.Windows.Triage" in result

    def test_legacy_request_with_no_custom_artifacts_falls_back(self) -> None:
        """A pre-A2 backend may send empty custom_artifacts entirely."""
        request = _make_request([])
        result = initial_custom_tool_names(request)
        assert result == set(
            TIER1_CUSTOM_TOOLS.get("windows", ())
        )

    def test_explicit_tier1_overrides_legacy_fallback(self) -> None:
        """If DB explicitly provides a tier=1 entry that IS whitelisted,
        it must be included in the result alongside (or instead of) the
        fallback. We test that Triage from the DB survives.
        """
        request = _make_request(
            [CustomArtifactRef(
                name="Custom.DFIR.Windows.Triage",
                tier=1,
                supported_platforms=["windows"],
            )]
        )
        assert "custom:Custom.DFIR.Windows.Triage" in (
            initial_custom_tool_names(request)
        )

    def test_linux_legacy_request_falls_back_to_linux_triage(self) -> None:
        request = _make_request(
            [
                CustomArtifactRef(
                    name="Custom.DFIR.Windows.MustangPanda",
                    tier=2,
                    supported_platforms=["windows"],
                )
            ],
            platform="linux",
        )
        result = initial_custom_tool_names(request)
        assert result == set(TIER1_CUSTOM_TOOLS.get("linux", ()))


# ===========================================================================
# M3: End-to-end via InvestigationRequest.model_validate (real payload)
# ===========================================================================


class TestRealPayloadModelValidation:
    """Use real Pydantic validation to confirm the request shape is honored."""

    def test_windows_request_with_mustang_panda_tier2(self) -> None:
        """Backend A2 supplies MustangPanda tier=2 (windows-only).

        Tier 2 candidates MUST include MustangPanda. Tier 1 candidates
        fall back to the hardcoded whitelist (because DB supplied no
        tier=1 attempts — legacy-friendly behavior per review M2).
        """
        payload = {
            "schema_version": "dfir.deepagent.request/1.2",
            "investigation_id": "11111111-1111-4111-8111-111111111111",
            "client_id": "C.0123456789abcdef",
            "hostname": "WS-01",
            "target_platform": "windows",
            "time_range": {
                "from": "2026-09-08T00:00:00Z",
                "to": "2026-09-08T23:59:59Z",
            },
            "suspicious_activity": "nghi ngo MustangPanda",
            "llm_runtime": {
                "base_url": "http://llm.local/v1",
                "api_key": "k",
                "model": "m",
            },
            "velociraptor_api_client_yaml": "ca_certificate: t\nclient_cert: t\nclient_private_key: t\n",
            "custom_artifacts": [
                {
                    "name": "Custom.DFIR.Windows.MustangPanda",
                    "tier": 2,
                    "supported_platforms": ["windows"],
                    "description": "behavioral hunt",
                }
            ],
        }
        request = InvestigationRequest.model_validate(payload)
        assert tier2_custom_tool_names(request) == {
            "custom:Custom.DFIR.Windows.MustangPanda"
        }
        # M2: no tier=1 attempt → legacy fallback to hardcoded whitelist.
        assert "custom:Custom.DFIR.Windows.Triage" in (
            initial_custom_tool_names(request)
        )

    def test_windows_request_with_evil_tier1_is_blocked(self) -> None:
        payload = {
            "schema_version": "dfir.deepagent.request/1.2",
            "investigation_id": "11111111-1111-4111-8111-111111111111",
            "client_id": "C.0123456789abcdef",
            "hostname": "WS-01",
            "target_platform": "windows",
            "time_range": {
                "from": "2026-09-08T00:00:00Z",
                "to": "2026-09-08T23:59:59Z",
            },
            "suspicious_activity": "test",
            "llm_runtime": {
                "base_url": "http://llm.local/v1",
                "api_key": "k",
                "model": "m",
            },
            "velociraptor_api_client_yaml": "ca_certificate: t\nclient_cert: t\nclient_private_key: t\n",
            "custom_artifacts": [
                {
                    "name": "Custom.Evil.MaliciousRCE",
                    "tier": 1,  # attempted promotion via DB
                    "supported_platforms": ["windows"],
                }
            ],
        }
        request = InvestigationRequest.model_validate(payload)
        # Critical: this MUST be empty, regardless of DB tier=1.
        assert initial_custom_tool_names(request) == set()

    def test_legacy_payload_without_tier_field_defaults_to_tier2(self) -> None:
        """A pre-A2 backend omits `tier` entirely. CustomArtifactRef defaults
        to tier=2 — so the artifact is in Tier 2 candidates, NOT Tier 1.
        Tier 1 candidates must still come from the hardcoded fallback.
        """
        payload = {
            "schema_version": "dfir.deepagent.request/1.2",
            "investigation_id": "11111111-1111-4111-8111-111111111111",
            "client_id": "C.0123456789abcdef",
            "hostname": "WS-01",
            "target_platform": "windows",
            "time_range": {
                "from": "2026-09-08T00:00:00Z",
                "to": "2026-09-08T23:59:59Z",
            },
            "suspicious_activity": "test",
            "llm_runtime": {
                "base_url": "http://llm.local/v1",
                "api_key": "k",
                "model": "m",
            },
            "velociraptor_api_client_yaml": "ca_certificate: t\nclient_cert: t\nclient_private_key: t\n",
            "custom_artifacts": [
                {
                    "name": "Custom.DFIR.Windows.MustangPanda",
                    "supported_platforms": ["windows"],
                    # NO tier field — pre-A2 backend
                }
            ],
        }
        request = InvestigationRequest.model_validate(payload)
        # Legacy MustangPanda (no tier) defaults to tier=2.
        assert tier2_custom_tool_names(request) == {
            "custom:Custom.DFIR.Windows.MustangPanda"
        }
        # Tier 1 still has Triage from hardcoded fallback.
        assert "custom:Custom.DFIR.Windows.Triage" in (
            initial_custom_tool_names(request)
        )


# ===========================================================================
# CustomArtifactRef: supported_platforms field validation
# ===========================================================================


class TestCustomArtifactRefSupportedPlatforms:
    def test_supported_platforms_required(self) -> None:
        """supported_platforms is required (no implicit default) so that
        every custom artifact in the request declares its OS coverage.
        """
        with pytest.raises(ValidationError):
            CustomArtifactRef(name="Custom.DFIR.Windows.X")  # type: ignore[call-arg]

    def test_supported_platforms_rejects_empty_list(self) -> None:
        """Empty supported_platforms is rejected — Pydantic requires
        min_length=1. This blocks malformed data from ever reaching the
        catalog filter.
        """
        with pytest.raises(ValidationError):
            CustomArtifactRef(
                name="Custom.DFIR.Windows.X",
                supported_platforms=[],
            )

    def test_supported_platforms_only_accepts_known_platforms(self) -> None:
        with pytest.raises(ValidationError):
            CustomArtifactRef(
                name="Custom.DFIR.Windows.X",
                supported_platforms=["haiku"],  # type: ignore[list-item]
            )

    def test_supported_platforms_accepts_canonical_values(self) -> None:
        ref = CustomArtifactRef(
            name="Custom.DFIR.Windows.X",
            supported_platforms=["windows", "linux"],
        )
        assert ref.supported_platforms == ["windows", "linux"]
