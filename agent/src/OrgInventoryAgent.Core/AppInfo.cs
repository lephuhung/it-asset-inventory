namespace OrgInventoryAgent.Core;

/// <summary>
/// Thông tin định danh, đơn vị phát triển, mục đích và tính năng của OrgInventory Agent.
/// Bảo đảm tính minh bạch, công khai về quyền hạn và mục đích thu thập dữ liệu.
/// </summary>
public static class AppInfo
{
    public static readonly string Version =
        typeof(AppInfo).Assembly.GetName().Version?.ToString(3) ?? "1.0.0";

    public const string Name = "OrgInventory Agent";
    public const string FullTitle = "Hệ thống Quản lý Tài sản Công nghệ Thông tin & Đánh giá An toàn Thông tin";

    public const string Developer = "Phòng An ninh mạng và phòng, chống tội phạm sử dụng công nghệ cao, Công an tỉnh Hà Tĩnh";
    public const string DeveloperShort = "Phòng ANM & PCTP sử dụng CNC, Công an Hà Tĩnh";
    public const string Organization = "Công an tỉnh Hà Tĩnh";

    public const string Purpose =
        "Quản lý tài sản công nghệ thông tin, tự động kiểm kê cấu hình phần cứng, " +
        "danh mục phần mềm cài đặt và đánh giá trạng thái an toàn thông tin (Security Posture), " +
        "phục vụ công tác bảo đảm an ninh mạng và an toàn thông tin trong các cơ quan, đơn vị.";

    public const string TransparencyAndSafetyCommitment =
        "1. Chế độ hoạt động chỉ đọc (Read-only): Chỉ truy xuất thông số hệ thống qua WMI và Registry chuẩn, không thay đổi hay can thiệp vào cấu hình máy trạm.\n" +
        "2. Bảo vệ dữ liệu riêng tư: Tuyệt đối không đọc tài liệu, email, tin nhắn, mật khẩu, lịch sử duyệt web hay dữ liệu cá nhân của người dùng.\n" +
        "3. Bảo mật mTLS & Khóa cục bộ: Khóa bí mật (Private Key) được sinh và lưu trữ an toàn trong Windows Certificate Store, không bao giờ gửi ra ngoài.\n" +
        "4. Minh bạch & Mã nguồn kiểm soát: Tiến trình chạy ngầm minh bạch, nhật ký ghi cục bộ rõ ràng tại %ProgramData%\\OrgInventory\\logs phục vụ kiểm toán.";

    public static readonly string[] Features = new[]
    {
        "Định danh thiết bị đa nguồn: Nhận diện máy tính qua SMBIOS UUID, MachineGuid và Mainboard Serial có thuật toán trọng số chống trùng lặp.",
        "Kiểm kê chi tiết phần cứng: Thu thập thông số CPU, RAM, Ổ đĩa (SSD/HDD/NVMe), GPU, Bo mạch chủ, BIOS, Card mạng.",
        "Kiểm kê danh mục phần mềm: Quét danh sách ứng dụng đã cài đặt trên hệ điều hành (Registry HKLM, WOW6432Node và HKCU per-user).",
        "Đánh giá An toàn thông tin (Security Posture): Giám sát trạng thái Antivirus (Defender / bên thứ 3), bản cập nhật Windows Update, mã hóa BitLocker, Firewall, UAC, Secure Boot, chính sách chặn USB Storage.",
        "Kiểm tra cấu hình bảo mật nâng cao: Quét các cổng mạng đang mở (Listening Ports), phần mềm khởi động cùng Windows (Startup Programs), danh sách tài khoản nội bộ (Local Accounts), kiểm tra giao thức yếu (SMBv1, TLS 1.0, TLS 1.1, SSL 3.0).",
        "Phát hiện máy đa mạng (Dual-homed Detection): Tự động phát hiện thiết bị kết nối đồng thời nhiều mạng vật lý/ảo để cảnh báo nguy cơ bắc cầu mạng trái phép.",
        "Kênh truyền bảo mật xác thực 2 chiều (mTLS): Toàn bộ kết nối về máy chủ được mã hóa và xác thực bằng chứng chỉ số ECDSA P-256.",
        "Đồng bộ cấu hình động 2 chiều (2-way Config Sync): Tự động nhận và áp dụng cấu hình tần suất giám sát từ máy chủ chỉ trong ~30 giây.",
        "Hỗ trợ máy tính vùng cách ly (Offline Bundle 1-Click): Đóng gói dữ liệu kiểm kê cho máy không có mạng Internet, ký số ECDSA P-256 và mã hóa lai AES-256-GCM + RSA để chuyển qua USB an toàn."
    };
}
