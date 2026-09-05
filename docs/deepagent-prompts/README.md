# DeepAgent system prompt registry

Thư mục này lưu các snapshot bất biến của `system_prompt` dùng cho DeepAgent.
Khi tạo phiên bản mới, không sửa file phiên bản cũ: sao chép prompt hiện tại sang file
`system-prompt-vN-<name>.md`, tính lại SHA-256 sau khi trim khoảng trắng đầu/cuối, rồi
thêm một dòng vào bảng dưới đây.

| Phiên bản | Ngày | Trạng thái | Fingerprint | Mục đích |
| --- | --- | --- | --- | --- |
| [v1 — platform-aware](system-prompt-v1-platform-aware.md) | 2026-09-04 | archived | `cac43a583082` | Chọn tool theo nền tảng và catalog |
| [v2 — tiered](system-prompt-v2-tiered.md) | 2026-09-05 | archived | `f8c7dcf15ab0` | Triage Tier 1 rồi mở rộng tối đa một Tier 2 |
| [v3 — recall-first](system-prompt-v3-recall-first.md) | 2026-09-05 | current | `2ef2bd503e4e` | Không bỏ sót nhóm tín hiệu và hỗ trợ tối đa hai Tier 2 độc lập |

File tương thích [deepagent-platform-aware-triage-prompt.md](../deepagent-platform-aware-triage-prompt.md)
là working copy của phiên bản hiện tại. Snapshot có trạng thái `current` là nguồn chuẩn để
copy vào trường `system_prompt` trong cấu hình LLM & DFIR.

## Quy ước phát hành

1. Mỗi file phiên bản phải chứa nguyên prompt trong đúng một code block `text`.
2. Fingerprint là 12 ký tự đầu của SHA-256 trên nội dung prompt sau khi trim.
3. Không thay đổi snapshot đã phát hành; mọi thay đổi nội dung tạo phiên bản mới.
4. Chỉ một phiên bản có trạng thái `current`.
5. Ghi rõ thay đổi hành vi, giới hạn code tương ứng và ma trận đánh giá cần chạy.
