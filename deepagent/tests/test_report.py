from __future__ import annotations

from datetime import UTC, datetime, timedelta

from deepagent.models import Assessment, EvidenceItem, Finding, InvestigationRequest
from deepagent.report import build_markdown_report


def test_report_has_schema_front_matter_and_eight_ordered_sections() -> None:
    now = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
    request = InvestigationRequest(
        investigation_id="11111111-1111-4111-8111-111111111111",
        client_id="C.0123456789abcdef",
        hostname="WS-01",
        target_platform="windows",
        time_range={
            "from": (now - timedelta(hours=1)).isoformat(),
            "to": now.isoformat(),
        },
        suspicious_activity="Kiểm tra endpoint",
        llm_runtime={
            "base_url": "http://llm.local/v1",
            "api_key": "test-key",
            "model": "test-model",
        },
        velociraptor_api_client_yaml=(
            "ca_certificate: test\nclient_cert: test\nclient_private_key: test\n"
        ),
    )
    assessment = Assessment(
        severity="medium",
        confidence="medium",
        executive_summary="Có một dấu hiệu cần xác minh.",
        conclusion="Chưa đủ bằng chứng xác nhận xâm nhập.",
        findings=[
            Finding(
                id="F-001",
                title="Tiến trình cần rà soát",
                severity="medium",
                confidence="medium",
                status="observed",
                evidence_refs=["E-001"],
                evidence="Tiến trình xuất hiện trong kết quả thu thập.",
                recommendation="Xác minh chữ ký và nguồn thực thi.",
            )
        ],
        limitations=["Chỉ thu thập triage ban đầu."],
    )
    evidence = [
        EvidenceItem(
            evidence_id="E-001",
            tool="windows_pslist",
            collected_at=datetime(2026, 9, 5, 0, 45, tzinfo=UTC),
            ok=True,
            data=[{"Name": "example.exe"}],
        )
    ]

    report = build_markdown_report(request, assessment, evidence)

    assert report.startswith("---\nschema_version: dfir.report/1.0\n")
    headings = [
        "## 1. Tóm tắt",
        "## 2. Phạm vi và nguồn dữ liệu",
        "## 3. Phát hiện",
        "## 4. IoC",
        "## 5. Dòng thời gian",
        "## 6. Đánh giá và kết luận",
        "## 7. Khuyến nghị",
        "## 8. Hạn chế",
    ]
    positions = [report.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "2026-09-05T00:45:00+00:00" in report
    assert "Xác minh chữ ký và nguồn thực thi." in report
