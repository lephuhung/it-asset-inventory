namespace OrgInventoryAgent.Linux;

/// <summary>
/// Thông tin định danh, đơn vị phát triển, mục đích và tính năng của OrgInventory Agent (Linux).
/// Bảo đảm tính minh bạch, công khai về quyền hạn và mục đích thu thập dữ liệu.
/// </summary>
public static class AppInfo
{
    public static readonly string Version =
        typeof(AppInfo).Assembly.GetName().Version?.ToString(3) ?? "1.0.0";

    public const string Name = "OrgInventory Agent";
    public const string FullTitle = "Hệ thống Quản lý Tài sản Công nghệ Thông tin & Đánh giá An toàn Thông tin";
    public const string Platform = "Linux (x64 / arm64)";

    public const string Developer = "Phòng An ninh mạng và phòng, chống tội phạm sử dụng công nghệ cao, Công an tỉnh Hà Tĩnh";
    public const string DeveloperShort = "Phòng ANM & PCTP sử dụng CNC, Công an Hà Tĩnh";
    public const string Organization = "Công an tỉnh Hà Tĩnh";

    public const string Purpose =
        "Quản lý tài sản công nghệ thông tin, tự động kiểm kê cấu hình phần cứng, " +
        "danh mục phần mềm cài đặt và đánh giá trạng thái an toàn thông tin (Security Posture), " +
        "phục vụ công tác bảo đảm an ninh mạng và an toàn thông tin trong các cơ quan, đơn vị.";

    public const string TransparencyAndSafetyCommitment =
        "1. Chế độ hoạt động chỉ đọc (Read-only): Chỉ truy xuất thông số hệ thống qua /sys, /proc, dpkg/rpm, systemd và NetworkInterface chuẩn; không thay đổi hay can thiệp vào cấu hình máy trạm.\n" +
        "2. Bảo vệ dữ liệu riêng tư: Tuyệt đối không đọc tài liệu, email, tin nhắn, mật khẩu, lịch sử duyệt web hay dữ liệu cá nhân của người dùng.\n" +
        "3. Bảo mật mTLS & Khóa cục bộ: Khóa bí mật (Private Key) được sinh và lưu trữ an toàn dưới dạng PEM file với quyền 0600 trong /etc/orginventory/, không bao giờ gửi ra ngoài.\n" +
        "4. Minh bạch & Mã nguồn kiểm soát: Tiến trình chạy nền minh bạch (systemd unit), nhật ký ghi cục bộ rõ ràng tại /var/lib/orginventory/logs phục vụ kiểm toán.";

    public static readonly string[] Features = new[]
    {
        "Định danh thiết bị đa nguồn: Nhận diện máy tính qua SMBIOS UUID (/sys/class/dmi/id), Machine ID (/etc/machine-id) và Mainboard Serial có thuật toán trọng số chống trùng lặp.",
        "Kiểm kê chi tiết phần cứng: Thu thập thông số CPU (/proc/cpuinfo), RAM (/proc/meminfo), Ổ đĩa (/sys/block — SSD/HDD/NVMe), Mainboard, BIOS, Card mạng.",
        "Kiểm kê danh mục phần mềm: Quét danh sách gói cài đặt qua dpkg (Debian/Ubuntu), rpm (RHEL/CentOS/Fedora), pacman (Arch) và user-space binaries trong /usr/bin, /usr/local/bin, /opt.",
        "Đánh giá An toàn thông tin (Security Posture): Giám sát trạng thái Firewall (nftables/iptables/ufw), SELinux/AppArmor, unattended-upgrades, USB Storage restrictions, sudo policy, kernel version, SSH hardening.",
        "Kiểm tra cấu hình bảo mật nâng cao: Quét các cổng mạng đang mở (Listening TCP ports), systemd services đang chạy, danh sách tài khoản người dùng (/etc/passwd), phát hiện SSH daemon và weak SSH config.",
        "Phát hiện máy đa mạng (Dual-homed Detection): Tự động phát hiện thiết bị kết nối đồng thời nhiều mạng vật lý/ảo để cảnh báo nguy cơ bắc cầu mạng trái phép.",
        "Kênh truyền bảo mật xác thực 2 chiều (mTLS): Toàn bộ kết nối về máy chủ được mã hóa và xác thực bằng chứng chỉ số ECDSA P-256 (PEM file mode 0600).",
        "Đồng bộ cấu hình động 2 chiều (2-way Config Sync): Tự động nhận và áp dụng cấu hình tần suất giám sát từ máy chủ chỉ trong ~30 giây.",
        "Hỗ trợ máy tính vùng cách ly (Offline Bundle 1-Click): Đóng gói dữ liệu kiểm kê cho máy không có mạng Internet, ký số ECDSA P-256 và mã hóa lai AES-256-GCM + RSA để chuyển qua USB an toàn."
    };
}