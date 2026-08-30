"""System prompt tiếng Việt cho DFIR AI Assistant."""


def build_dfir_system_prompt() -> str:
    """System prompt mặc định."""
    return """Bạn là chuyên gia Digital Forensics & Incident Response (DFIR) hỗ trợ \
Phòng An ninh mạng và phòng, chống tội phạm sử dụng công nghệ cao, Công an tỉnh Hà Tĩnh.

NGUYÊN TẮC BẮT BUỘC:
1. Trả lời bằng tiếng Việt, ngôn ngữ chuyên nghiệp, súc tích.
2. CHỈ dựa trên dữ liệu được cung cấp — KHÔNG suy đoán, KHÔNG bịa thêm sự kiện.
3. Nếu dữ liệu không đủ để kết luận, nói rõ "Cần thu thập thêm...".
4. Luôn đánh giá mức độ nghiêm trọng theo thang: critical | high | medium | low | info.
5. Khi phát hiện chỉ báo tấn công (IoC), tham chiếu MITRE ATT&CK technique ID nếu biết.

ĐỊNH DẠNG BÁO CÁO (BẮT BUỘC theo cấu trúc Markdown):
# Báo cáo điều tra máy [hostname]
**Mức độ nghiêm trọng:** [critical/high/medium/low/info]
**Số phát hiện:** [N]

## 1. Tóm tắt điều hành (Executive Summary)
[2-4 câu tổng quan cho lãnh đạo]

## 2. Phát hiện chi tiết
### 2.1 [Tiêu đề phát hiện 1]
- **Mô tả:** ...
- **Bằng chứng:** ... (dòng log cụ thể)
- **MITRE ATT&CK:** Txxxx - Tên kỹ thuật (nếu áp dụng)
- **Mức độ:** ...

## 3. Dấu hiệu IoC (Indicators of Compromise)
- Hash: ...
- IP: ...
- Domain: ...
- Process path: ...

## 4. Đề xuất hành động
1. [Hành động khẩn cấp - thực hiện trong 1 giờ]
2. [Hành động quan trọng - trong 24 giờ]
3. [Hành động theo dõi - trong tuần]

## 5. Hạn chế của dữ liệu
[Liệt kê những gì CHƯA có để kết luận chắc chắn]

Khi user hỏi tiếp (Q&A), trả lời ngắn gọn, dùng lại context từ data đã thu thập."""


def build_investigation_user_prompt(
    *,
    hostname: str,
    os_info: dict,
    artifacts_data: dict[str, list[dict]],
    custom_instructions: str | None = None,
    max_chars: int = 200_000,
) -> str:
    """User prompt cho investigation — bundle dữ liệu Velociraptor."""
    parts: list[str] = []
    parts.append(f"# Dữ liệu điều tra máy `{hostname}`\n")
    parts.append("## Thông tin hệ thống")
    parts.append(f"- OS: {os_info.get('system', '?')} {os_info.get('release', '')}")
    parts.append(f"- Kiến trúc: {os_info.get('architecture', '?')}")
    parts.append(f"- FQDN: {os_info.get('fqdn', '?')}")
    parts.append("")

    for artifact_name, rows in artifacts_data.items():
        if not rows:
            continue
        parts.append(f"## Artifact: `{artifact_name}` ({len(rows)} dòng)")
        sample = rows[:200]
        for row in sample:
            kv = " | ".join(
                f"{k}={_safe(v)}" for k, v in row.items() if v not in (None, "", [])
            )
            if kv:
                parts.append(f"  - {kv}")
        if len(rows) > 200:
            parts.append(f"  - ... và {len(rows) - 200} dòng nữa (đã lược bớt)")
        parts.append("")

    if custom_instructions:
        parts.append("---")
        parts.append(f"**Yêu cầu đặc biệt từ điều tra viên:** {custom_instructions}")
        parts.append("")

    parts.append("---")
    parts.append("Hãy phân tích dữ liệu trên và trả về báo cáo theo cấu trúc đã định.")

    full = "\n".join(parts)
    if len(full) > max_chars:
        full = full[:max_chars] + "\n\n[DỮ LIỆU ĐÃ CẮT BỚT DO QUÁ DÀI]"
    return full


def build_chat_user_prompt(question: str) -> str:
    """User prompt cho câu hỏi Q&A tiếp theo."""
    return (
        f"Câu hỏi tiếp theo của điều tra viên: {question}\n\n"
        "Trả lời ngắn gọn, dựa trên dữ liệu đã thu thập ở trên. "
        "Nếu không đủ dữ liệu để trả lời, đề xuất artifact cần thu thập thêm."
    )


def _safe(v: object) -> str:
    """Stringify an toàn, cắt dài, loại bỏ ký tự xuống dòng."""
    s = str(v)
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) > 200:
        s = s[:200] + "..."
    return s
