from __future__ import annotations

from deepagent.models import Assessment, EvidenceItem, InvestigationRequest


def _clean(value: str) -> str:
    return value.replace("\x00", "").replace("<script", "&lt;script")


def build_markdown_report(
    request: InvestigationRequest,
    assessment: Assessment,
    evidence: list[EvidenceItem],
) -> str:
    successful = sum(1 for item in evidence if item.ok)
    failed = len(evidence) - successful
    lines = [
        f"# Báo cáo điều tra máy {_clean(request.hostname)}",
        "",
        f"**Client ID:** `{request.client_id}`  ",
        f"**Khoảng thời gian:** `{request.time_range.from_.isoformat()}` đến `{request.time_range.to.isoformat()}`  ",
        f"**Mức độ:** `{assessment.severity}`  ",
        f"**Độ tin cậy:** `{assessment.confidence}`  ",
        f"**Số phát hiện:** `{len(assessment.findings)}`",
        "",
        "## 1. Tóm tắt điều hành",
        "",
        _clean(assessment.executive_summary),
        "",
        "## 2. Phạm vi và nguồn dữ liệu",
        "",
        f"DeepAgent đã thực hiện {len(evidence)} truy vấn MCP read-only: {successful} thành công, {failed} lỗi.",
        "",
    ]
    for item in evidence:
        status = "thành công" if item.ok else f"lỗi: {_clean(item.error or 'không rõ')}"
        lines.append(f"- `{item.evidence_id}` — `{item.tool}` — {status}")

    lines.extend(["", "## 3. Phát hiện", ""])
    if not assessment.findings:
        lines.append("Không có phát hiện đủ bằng chứng trong phạm vi dữ liệu đã thu thập.")
    for finding in assessment.findings:
        refs = ", ".join(f"`{ref}`" for ref in finding.evidence_refs)
        lines.extend(
            [
                f"### {finding.id} — {_clean(finding.title)}",
                "",
                f"- **Phân loại:** `{finding.status}`",
                f"- **Mức độ:** `{finding.severity}`",
                f"- **Độ tin cậy:** `{finding.confidence}`",
                f"- **Bằng chứng:** {refs} — {_clean(finding.evidence)}",
                f"- **MITRE ATT&CK:** `{finding.mitre_id or 'N/A'}`",
                f"- **Khuyến nghị:** {_clean(finding.recommendation)}",
                "",
            ]
        )

    lines.extend(["## 4. Dấu hiệu IoC", ""])
    if assessment.iocs:
        for ioc in assessment.iocs:
            lines.append(f"- **{ioc.type}:** `{_clean(ioc.value)}` — nguồn `{ioc.evidence_ref}`")
    else:
        lines.append("Không trích xuất được IoC có nguồn bằng chứng hợp lệ.")

    lines.extend(
        [
            "",
            "## 5. Đánh giá và kết luận",
            "",
            _clean(assessment.conclusion),
            "",
            "## 6. Hạn chế",
            "",
        ]
    )
    limitations = list(assessment.limitations)
    limitations.extend(
        f"Truy vấn `{item.tool}` thất bại: {item.error}" for item in evidence if not item.ok
    )
    if limitations:
        lines.extend(f"- {_clean(item)}" for item in limitations)
    else:
        lines.append("- Không ghi nhận hạn chế bổ sung ngoài phạm vi thời gian đã chỉ định.")
    return "\n".join(lines).strip() + "\n"
