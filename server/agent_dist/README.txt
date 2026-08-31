═══════════════════════════════════════════════════════════════════════════════
  AGENT BUNDLE — OrgInventory + Velociraptor (cài trong 1 lần)
═══════════════════════════════════════════════════════════════════════════════

Đơn vị: Phòng An ninh mạng và phòng, chống tội phạm sử dụng công nghệ cao
        Công an tỉnh Hà Tĩnh

───────────────────────────────────────────────────────────────────────────────
  CÀI ĐẶT NHANH (3 bước)
───────────────────────────────────────────────────────────────────────────────

  1. Copy file agent-bundle-windows.zip lên máy Windows cần giám sát.

  2. Extract zip vào 1 thư mục bất kỳ, ví dụ:
       C:\Temp\agent-bundle\

  3. Right-click file "install-all.bat" → chọn "Run as administrator"

     Script sẽ tự hỏi:
       - Endpoint (URL Inventory Server, vd https://agent.gov.vn)
       - Token (Enroll Token lấy từ Portal → tab "Deploy")

     Hoặc truyền trước qua PowerShell:
       $env:ORGINVENTORY_ENDPOINT="https://agent.gov.vn"
       $env:ORGINVENTORY_TOKEN="t_abc123xyz"
       .\install-all.bat

───────────────────────────────────────────────────────────────────────────────
  CÁCH HOẠT ĐỘNG
───────────────────────────────────────────────────────────────────────────────

  Script cài 2 service tuần tự:

  �─ BUOC 1 ─ OrgInventory Agent ─────────────────────────────────────┐
  │  • Cài MSI: OrgInventoryAgent.msi                                │
  │  • Truyền ENROLL_TOKEN + ENDPOINTS vào MSI                        │
  │  • Service: OrgInventoryAgent (Automatic)                        │
  │  • Enroll: token-based → mTLS cert với Inventory Server           │
  │  • Log: %ProgramData%\OrgInventory\logs\agent.log                 │
  └───────────────────────────────────────────────────────────────────┘

  ┌─ BUOC 2 ─ Velociraptor Client ────────────────────────────────────�
  │  • Cài MSI: velociraptor-windows-amd64.msi                        │
  │  • Copy client.config.yaml → C:\Program Files\Velociraptor\      │
  │  • Service: Velociraptor (Automatic)                              │
  │  • Enroll: gRPC với Velociraptor Server qua CA cert nhúng sẵn    │
  │  • Log: C:\Program Files\Velociraptor\logs\velociraptor.log      │
  └───────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
  KIỂM TRA SAU KHI CÀI
───────────────────────────────────────────────────────────────────────────────

  • Trên Windows (PowerShell):
      Get-Service OrgInventoryAgent, Velociraptor
        → cả 2 phải Running

  • Trên Inventory Portal (https://agent.gov.vn):
      Tab "Machines" → máy mới xuất hiện sau ~1 phút

  • Trên Velociraptor GUI (https://10.10.0.241:8889):
      Tab "Clients" → máy mới xuất hiện sau ~30 giây

───────────────────────────────────────────────────────────────────────────────
  GỠ CÀI ĐẶT
───────────────────────────────────────────────────────────────────────────────

  Vào Control Panel → Programs and Features, gỡ 2 entry:
    • Velociraptor Service Installer
    • OrgInventory Agent

  Hoặc PowerShell (admin):
    Get-WmiObject Win32_Product | Where-Object {$_.Name -like "*Velociraptor*"} | ForEach-Object { msiexec /x $_.IdentifyingNumber /qn }
    Get-WmiObject Win32_Product | Where-Object {$_.Name -like "*OrgInventory*"} | ForEach-Object { msiexec /x $_.IdentifyingNumber /qn }

───────────────────────────────────────────────────────────────────────────────
  KHẮC PHỤC SỰ CỐ
───────────────────────────────────────────────────────────────────────────────

  • Service không start    → xem log ở đường dẫn nêu trên
  • Không enroll được      → kiểm tra firewall (port 8888 + 9443 mở)
  • Token hết hạn         → lấy token mới từ Portal → Deploy
  • Velociraptor URL sai  → báo admin để regenerate client.config.yaml

───────────────────────────────────────────────────────────────────────────────
  LIÊN HỆ HỖ TRỢ
───────────────────────────────────────────────────────────────────────────────

  Phòng An ninh mạng — Công an tỉnh Hà Tĩnh
  Hotline nội bộ: <cập nhật khi triển khai>
═══════════════════════════════════════════════════════════════════════════════
