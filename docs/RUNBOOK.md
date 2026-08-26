# RUNBOOK VẬN HÀNH — IT Asset Inventory (Phase 1 MVP)

> Căn cứ: PLAN_THUC_HIEN.md mục 7 (bàn giao vận hành), KE_HOACH mục 3.5 (đổi endpoint), 7.3 (hardening).
> Vai trò: PM / Admin hệ thống / Đội an ninh cơ quan.

---

## 1. TRIỂN KHAI CƠ QUAN MỚI (checklist)

1. ☐ Bàn giao **hash + publisher cert** của `agent.msi`/`agent.exe`/`install.ps1` cho đội an ninh mạng để **whitelist AV tập trung** (BKAV Pro / Kaspersky Security Center / Defender GPO). *Làm trước khi cài đại trà.*
2. ☐ Submit Microsoft WDSI cho mỗi release binary mới.
3. ☐ Đăng ký tên miền + TLS cert (ACME/certbot), VD `inventory.<coquan>.gov.vn`.
4. ☐ Tạo org + admin cơ quan trên portal; bật 2FA TOTP cho admin.
5. ☐ Cập nhật bản thông báo tuân thủ pháp lý (compliance_notice) theo đúng dữ liệu thu thập + mục đích + thời hạn lưu trữ (NĐ 13/2023/NĐ-CP).
6. ☐ Thử nghiệm pilot 5–10 máy thật 1 tuần trước khi mở rộng (tiêu chí Go/No-Go mục 4 PLAN).

## 2. ĐỔI IP/DOMAIN SERVER (mục 3.5 tài liệu gốc)

1. Dựng server mới chạy **song song**; giảm DNS TTL ≥ 1 ngày trước.
2. Đẩy config endpoint mới cho agent (Phase 3: signed config push; trước đó: thay config tay qua MSI repair hoặc cập nhật file config trong ProgramData theo kênh nội bộ).
3. Theo dõi tỉ lệ agent đã chuyển trên dashboard.
4. Khi ≥ 99% agent chuyển → tắt server cũ; giữ DNS cũ redirect thêm thời gian cho máy offline lâu ngày.

## 3. VÒNG ĐỜI CERT

- **Client cert agent**: tự renew ở ~70% vòng đời (RenewService). Cảnh báo sớm 30 ngày nếu tỉ lệ renew thất bại tăng.
- **Server TLS cert**: ACME/certbot tự gia hạn; cảnh báo ≥ 30 ngày trước hết hạn.
- **CA nội bộ (step-ca)**: root CA lưu **offline**; issuing CA trong KMS/HSM; CRL được cron tải về nginx + `nginx -s reload` (không downtime).
- Thanh lý/mất máy: thu hồi cert qua step-ca → CRL → agent bị chặn ở tầng TLS.

## 4. BACKUP & RESTORE

- Backup hàng ngày: PostgreSQL (pg_dump), Redis (rdb), config Vault.
- Backup **mã hóa**; test restore định kỳ với RPO/RTO đã định nghĩa (VD RPO 24h, RTO 4h).
- `audit_log` anchor ký định kỳ (Phase 2) lưu ra ngoài DB (object storage/file chỉ-ghi).

## 5. XỬ LÝ SỰ CỐ

| Sự cố | Triệu chứng | Xử lý |
|---|---|---|
| AV gắn cờ agent | Máy không cài được / agent bị xóa | Kiểm tra whitelist AV đã đẩy hash mới chưa; submit WDSI; liên hệ đội an ninh cơ quan |
| Máy "lost" hàng loạt | Dashboard thấy nhiều máy offline > N ngày | Kiểm tra cert client hết hạn (renew fail), CRL sai, mạng chặn 443, đổi domain chưa hoàn tất |
| Heartbeat trễ | Trạng thái online sai lệch | Kiểm tra Redis, load server, tăng heartbeat_interval_sec qua config |
| Agent không enroll | Token lỗi | Token 1 lần + TTL 72h — sinh token mới; kiểm tra đồng hồ máy (TLS cần clock đúng) |
| Giả header X-SSL-Client | Nghi ngờ request lạ vào thẳng FastAPI | FastAPI chỉ bind IP nội bộ + TRUSTED_PROXIES; kiểm tra firewall giữa nginx và app |
| Quá tải | API chậm, Redis nghẽn | Batch insert heartbeats, tăng chu kỳ heartbeat, scale worker |

## 6. BẢO TRÌ ĐỊNH KỲ

- Hàng tuần: xem dashboard, kiểm tra cảnh báo cert, tỉ lệ heartbeat thành công.
- Mỗi release: build agent mới → ký OV cert + timestamp → WDSI → cập nhật hash whitelist AV → release theo đợt.
- Mỗi quý: test restore backup 1 lần, review audit log hash chain, cập nhật runbook.

## 7. KHÔNG ĐƯỢC LÀM

- Không upload agent lên VirusTotal (phát tán mẫu → ML vendor học theo).
- Không thay đổi agent thành công cụ giám sát (screenshot/keylog/remote shell) — mục 6.6 tài liệu gốc.
- Không tắt mTLS/verify để "cho nhanh".
