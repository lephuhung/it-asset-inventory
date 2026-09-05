"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  AlertCircle,
  Building2,
  Check,
  CheckCircle2,
  Clock,
  Database,
  FileCheck,
  FileText,
  Headset,
  History,
  Lock,
  Mail,
  PhoneCall,
  Scale,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ComplianceNotice } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  PageHeader,
  Spinner,
} from "@/components/ui";

const DEFAULT_COMPLIANCE_MD = `# THÔNG BÁO TUÂN THỦ QUY ĐỊNH BẢO VỆ DỮ LIỆU CÁ NHÂN
*(Ban hành theo Nghị định số 13/2023/NĐ-CP của Chính phủ về bảo vệ dữ liệu cá nhân)*

Hệ thống Quản lý Tài sản Máy tính & Cổng thông tin nội bộ cam kết bảo vệ dữ liệu cá nhân và tuân thủ nghiêm ngặt các quy định pháp luật hiện hành của Việt Nam, đặc biệt là **Nghị định 13/2023/NĐ-CP**, Luật An toàn thông tin mạng 2015 và Luật An ninh mạng 2018.

---

### 1. Phạm vi thu thập và xử lý dữ liệu
- **Loại dữ liệu xử lý**: Hệ thống chỉ thu thập và xử lý các **Dữ liệu cá nhân cơ bản** (theo quy định tại Điều 2 Khoản 3 Nghị định 13/2023/NĐ-CP) cần thiết phục vụ quản lý, vận hành danh bạ và tài sản công nghệ thông tin:
  - **Họ và tên**: Định danh cán bộ, nhân sự được giao quản lý và sử dụng thiết bị.
  - **Số điện thoại**: Số điện thoại liên hệ phục vụ công tác của cá nhân.
  - **Nơi công tác của cá nhân**: Đơn vị công tác, cơ quan, phòng ban và chức danh / vị trí công tác của cán bộ.
  - **Thông tin thiết bị công tác liên kết**: Tên máy tính (Hostname), địa chỉ IP, cấu hình kỹ thuật phần cứng (CPU, RAM, Ổ cứng) và trạng thái kết nối trực tuyến của thiết bị được giao quản lý.
- **Cam kết KHÔNG thu thập**: Tuyệt đối **không thu thập dữ liệu cá nhân nhạy cảm** (vị trí định vị GPS thời gian thực của cá nhân, thông tin tài khoản ngân hàng, sinh trắc học cá nhân, nội dung tin nhắn/cuộc gọi riêng tư, lịch sử duyệt web hay thao tác bàn phím cá nhân).

---

### 2. Mục đích và cách thức xử lý dữ liệu
- **Mục đích xử lý**:
  - Quản trị, hiển thị và vận hành danh bạ cán bộ, nhân sự phụ trách thiết bị công nghệ thông tin trên website / cổng thông tin nội bộ.
  - Phục vụ đối soát tài sản máy tính công, hỗ trợ kỹ thuật, kịp thời xử lý sự cố an toàn thông tin và bảo vệ hệ thống công vụ của cơ quan, đơn vị.
- **Cách thức xử lý**:
  - Dữ liệu được tiếp nhận trực tiếp từ cá nhân hoặc đơn vị quản lý thông qua cổng thông tin hoặc quy trình cấp phát token đăng ký thiết bị.
  - Lưu trữ trong cơ sở dữ liệu nội bộ được bảo vệ nghiêm ngặt và chỉ hiển thị trong phạm vi phân quyền quản trị công vụ.
- **Cam kết sử dụng đúng mục đích**:
  - Ban quản trị **cam kết không sử dụng dữ liệu cho bất kỳ mục đích nào khác** ngoài các mục đích công vụ đã quy định nếu chưa được sự đồng ý của chủ thể dữ liệu.
  - Tuyệt đối không chuyển giao, chia sẻ, mua bán hoặc cung cấp dữ liệu cho bất kỳ bên thứ ba nào vì mục đích thương mại hoặc quảng cáo.

---

### 3. Thời hạn lưu trữ và bảo mật dữ liệu
- **Thời hạn lưu trữ**:
  - Cam kết thời hạn lưu trữ giới hạn theo mục đích xử lý: Dữ liệu cá nhân chỉ được lưu trữ trong suốt thời gian cá nhân còn công tác tại cơ quan, đơn vị hoặc còn chịu trách nhiệm quản trị/sử dụng tài sản trên hệ thống.
  - Khi cá nhân chuyển công tác, chấm dứt nhiệm vụ hoặc có yêu cầu xóa hợp lệ theo quy định, dữ liệu sẽ được tiến hành xóa bỏ an toàn hoặc ẩn danh hóa vĩnh viễn khỏi cơ sở dữ liệu vận hành.
- **Biện pháp kỹ thuật bảo vệ chống thất thoát, rò rỉ dữ liệu**:
  - **Mã hóa at-rest**: Số điện thoại và các trường dữ liệu nhạy cảm được mã hóa tự động bằng thuật toán **AES-256-GCM** trước khi ghi vào cơ sở dữ liệu.
  - **Mã hóa truyền tải**: Toàn bộ dữ liệu truyền nhận giữa website và máy trạm được bảo vệ qua kết nối mã hóa **HTTPS / TLS 1.3** và xác thực chứng chỉ số hai chiều (**mTLS**).
  - **Xác thực đa yếu tố & Phân quyền**: Bắt buộc kích hoạt xác thực hai yếu tố (**2FA / TOTP**) đối với tài khoản quản trị; kiểm soát quyền truy cập theo vai trò (**RBAC**) theo nguyên tắc đặc quyền tối thiểu.
  - **Nhật ký kiểm toán chống chối bỏ (Audit Log)**: Ghi nhật ký tự động mọi thao tác truy cập, chỉnh sửa dữ liệu vào sổ cái append-only theo chuỗi băm (hash chain) không thể tẩy xóa hay sửa đổi.
  - **Phòng chống thất thoát dữ liệu & Sao lưu định kỳ**: Hệ thống tự động giám sát phát hiện bất thường, sao lưu dữ liệu mã hóa định kỳ và duy trì kế hoạch ứng phó sự cố rò rỉ thông tin theo quy chuẩn an toàn thông tin cấp độ.

---

### 4. Quyền và nghĩa vụ của người dùng (Chủ thể dữ liệu)
- **Quyền hợp pháp của người dùng theo Nghị định 13/2023/NĐ-CP**:
  - **Quyền được biết**: Được thông báo rõ ràng, minh bạch về mọi hoạt động thu thập và xử lý dữ liệu cá nhân của mình.
  - **Quyền đồng ý & Rút lại sự đồng ý**: Người dùng có quyền đồng ý hoặc rút lại sự đồng ý cho phép xử lý dữ liệu cá nhân bất cứ lúc nào.
  - **Quyền truy cập & Xem**: Có quyền tra cứu, kiểm tra các thông tin cá nhân của mình đang được hệ thống lưu trữ.
  - **Quyền yêu cầu chỉnh sửa**: Có quyền yêu cầu ban quản trị cập nhật, sửa đổi khi phát hiện dữ liệu cá nhân bị sai lệch hoặc khi có thay đổi nơi công tác.
  - **Quyền yêu cầu xóa dữ liệu**: Có quyền yêu cầu xóa bỏ hoặc hạn chế xử lý dữ liệu cá nhân của mình theo quy định pháp luật.
  - **Quyền khiếu nại, phản ánh**: Có quyền gửi phản ánh, khiếu nại tới cơ quan quản lý khi nghi ngờ có hành vi xâm hại hoặc vi phạm an toàn dữ liệu cá nhân.
- **Nghĩa vụ của người dùng**:
  - Cung cấp thông tin trung thực, chính xác và kịp thời thông báo khi có sự thay đổi thông tin liên hệ / nơi công tác.
  - Tự bảo quản thông tin xác thực tài khoản cá nhân; nghiêm cấm việc khai thác, trích xuất dữ liệu của cá nhân khác khi chưa được phân công nhiệm vụ.

---

### 5. Đầu mối liên hệ giải quyết & Tiếp nhận yêu cầu
Mọi yêu cầu thực hiện quyền của chủ thể dữ liệu (rút lại sự đồng ý, yêu cầu tra cứu, chỉnh sửa hoặc xóa dữ liệu cá nhân) được tiếp nhận và xử lý qua các kênh chính thức sau:
- **Email tiếp nhận**: \`compliance@example.gov.vn\` *(hoặc \`privacy@gov.vn\`)*
- **Hotline hỗ trợ**: \`1900 xxxx\` / \`0239.xxx.xxxx\` (Tiếp nhận hỗ trợ trong giờ hành chính từ Thứ 2 đến Thứ 6)
- **Đơn vị tiếp nhận**: Bộ phận Quản trị Hệ thống & An toàn thông tin
- **Thời hạn giải quyết**: Cam kết xác nhận tiếp nhận và xử lý yêu cầu hợp lệ của chủ thể dữ liệu trong thời hạn tối đa không quá **72 giờ** làm việc kể từ thời điểm nhận được yêu cầu.
`;

const FALLBACK_NOTICE: ComplianceNotice = {
  id: "00000000-0000-0000-0000-000000000001",
  version: "1.0",
  title: "Thông báo Tuân thủ Quy định Bảo vệ Dữ liệu Cá nhân",
  content_md: DEFAULT_COMPLIANCE_MD,
  effective_from: new Date().toISOString(),
};

export default function CompliancePage() {
  const [notice, setNotice] = useState<ComplianceNotice | null>(null);
  const [pending, setPending] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ackBusy, setAckBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [current, hasPending] = await Promise.all([
        api.get<ComplianceNotice | null>("/compliance/current"),
        api.get<boolean>("/compliance/pending"),
      ]);
      setNotice(current ?? FALLBACK_NOTICE);
      setPending(hasPending);
      setError(null);
    } catch {
      // Khi offline / chưa cấu hình server, sử dụng bản thông báo chuẩn mặc định
      setNotice(FALLBACK_NOTICE);
      setPending(false);
      setError(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const acknowledge = async () => {
    if (!notice) return;
    setAckBusy(true);
    setError(null);
    try {
      await api.post("/compliance/acknowledge", { notice_id: notice.id });
      setPending(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không xác nhận được");
    } finally {
      setAckBusy(false);
    }
  };

  const activeNotice = notice ?? FALLBACK_NOTICE;

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        title="Thông báo tuân thủ & Bảo vệ dữ liệu cá nhân"
        description="Minh bạch việc thu thập, xử lý và bảo vệ dữ liệu — Tuân thủ Nghị định 13/2023/NĐ-CP, Luật An toàn thông tin mạng & Luật An ninh mạng"
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading ? (
        <Spinner label="Đang tải thông báo tuân thủ…" />
      ) : (
        <>
          {/* 5 Trụ cột cốt lõi tuân thủ */}
          <div className="rounded-xl border border-blue-100 bg-gradient-to-r from-blue-50/70 via-indigo-50/40 to-slate-50 p-5">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShieldCheck className="size-5 text-brand-600" />
                <h3 className="text-base font-semibold text-slate-800">
                  5 Nội Dung Cốt Lõi Về Bảo Vệ Dữ Liệu Cá Nhân
                </h3>
              </div>
              <Badge className="bg-blue-100 text-blue-700 ring-blue-600/20">
                Nghị định 13/2023/NĐ-CP
              </Badge>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
              {/* 1. Phạm vi thu thập */}
              <div className="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div>
                  <div className="flex items-center gap-2 text-brand-600">
                    <Database className="size-4" />
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                      Mục 1
                    </span>
                  </div>
                  <h4 className="mt-2 text-sm font-semibold text-slate-900">
                    Phạm vi dữ liệu
                  </h4>
                  <p className="mt-1 text-xs text-slate-600 leading-relaxed">
                    Chỉ xử lý <strong>dữ liệu cá nhân cơ bản</strong>: Số điện thoại, Nơi công tác (cơ quan/phòng ban/chức vụ) và thông tin thiết bị công tác.
                  </p>
                </div>
                <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-emerald-600 font-medium">
                  ✓ Không thu thập dữ liệu nhạy cảm
                </div>
              </div>

              {/* 2. Mục đích và cách thức */}
              <div className="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div>
                  <div className="flex items-center gap-2 text-indigo-600">
                    <FileCheck className="size-4" />
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                      Mục 2
                    </span>
                  </div>
                  <h4 className="mt-2 text-sm font-semibold text-slate-900">
                    Mục đích & Cam kết
                  </h4>
                  <p className="mt-1 text-xs text-slate-600 leading-relaxed">
                    Vận hành và hiển thị danh bạ cán bộ, tài sản công vụ trên website.
                  </p>
                </div>
                <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-indigo-700 font-medium">
                  ✓ Cam kết không dùng mục đích khác nếu chưa đồng ý
                </div>
              </div>

              {/* 3. Lưu trữ & Bảo mật */}
              <div className="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div>
                  <div className="flex items-center gap-2 text-amber-600">
                    <Lock className="size-4" />
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                      Mục 3
                    </span>
                  </div>
                  <h4 className="mt-2 text-sm font-semibold text-slate-900">
                    Lưu trữ & Bảo mật
                  </h4>
                  <p className="mt-1 text-xs text-slate-600 leading-relaxed">
                    Thời hạn lưu trữ <strong>giới hạn theo mục đích</strong> công vụ. Áp dụng mã hóa AES-256, mTLS, Audit Log chống rò rỉ thất thoát.
                  </p>
                </div>
                <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-amber-700 font-medium">
                  ✓ Mã hóa at-rest & transit
                </div>
              </div>

              {/* 4. Quyền của chủ thể dữ liệu */}
              <div className="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div>
                  <div className="flex items-center gap-2 text-rose-600">
                    <UserCheck className="size-4" />
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                      Mục 4
                    </span>
                  </div>
                  <h4 className="mt-2 text-sm font-semibold text-slate-900">
                    Quyền người dùng
                  </h4>
                  <p className="mt-1 text-xs text-slate-600 leading-relaxed">
                    Đảm bảo các quyền hợp pháp: <strong>rút lại sự đồng ý</strong>, quyền yêu cầu <strong>chỉnh sửa hoặc xóa</strong> dữ liệu cá nhân.
                  </p>
                </div>
                <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-rose-600 font-medium">
                  ✓ Rút đồng ý, sửa & xóa
                </div>
              </div>

              {/* 5. Đầu mối liên hệ */}
              <div className="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div>
                  <div className="flex items-center gap-2 text-emerald-600">
                    <Headset className="size-4" />
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                      Mục 5
                    </span>
                  </div>
                  <h4 className="mt-2 text-sm font-semibold text-slate-900">
                    Đầu mối tiếp nhận
                  </h4>
                  <p className="mt-1 text-xs text-slate-600 leading-relaxed">
                    Kênh tiếp nhận chính thức qua <strong>Email & Hotline</strong> để hỗ trợ người dùng thực hiện các quyền bảo vệ dữ liệu.
                  </p>
                </div>
                <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-emerald-700 font-medium">
                  ✓ Phản hồi trong tối đa 72h
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            {/* Văn bản thông báo tuân thủ chi tiết */}
            <Card
              className="lg:col-span-2"
              title={
                <span className="inline-flex items-center gap-2">
                  <FileText className="size-4 text-brand-600" />
                  {activeNotice.title}
                  <Badge className="bg-brand-50 text-brand-700 ring-brand-600/20">
                    v{activeNotice.version}
                  </Badge>
                </span>
              }
              subtitle={`Hiệu lực từ ${new Date(activeNotice.effective_from).toLocaleDateString("vi-VN")}`}
            >
              <div className="prose prose-slate max-w-none text-sm text-slate-700 prose-headings:text-slate-900 prose-h3:text-base prose-h3:font-bold prose-h3:mt-6 prose-h3:mb-3 prose-p:leading-relaxed prose-li:my-1">
                <ReactMarkdown>{activeNotice.content_md}</ReactMarkdown>
              </div>
            </Card>

            {/* Sidebar thông tin trạng thái, đầu mối, căn cứ */}
            <div className="space-y-5">
              {/* Trạng thái xác nhận */}
              <Card title="Trạng thái xác nhận của bạn">
                {pending === null ? (
                  <p className="text-sm text-slate-500">Đang kiểm tra…</p>
                ) : pending ? (
                  <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
                    <Clock className="mt-0.5 size-4 shrink-0" />
                    <span>
                      Bạn chưa xác nhận bản này — hệ thống yêu cầu xác nhận trước khi tiếp tục thao tác.
                    </span>
                  </div>
                ) : (
                  <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-700">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                    Bạn đã xác nhận bản thông báo tuân thủ hiện hành.
                  </div>
                )}
                {pending && (
                  <Button
                    className="mt-3 w-full"
                    onClick={() => void acknowledge()}
                    loading={ackBusy}
                  >
                    <Check className="size-4" /> Tôi đã đọc và đồng ý
                  </Button>
                )}
                <p className="mt-3 text-xs leading-relaxed text-slate-400">
                  Hành vi xác nhận được lưu vết vào bảng <code>user_acknowledgments</code> kèm thời gian, địa chỉ IP và ghi nhật ký Audit Log chống chối bỏ.
                </p>
              </Card>

              {/* Đầu mối hỗ trợ tiếp nhận yêu cầu */}
              <Card title="Kênh tiếp nhận & Hỗ trợ">
                <div className="space-y-3 text-sm text-slate-700">
                  <div className="flex items-start gap-2.5">
                    <Mail className="mt-0.5 size-4 text-brand-600 shrink-0" />
                    <div>
                      <span className="text-xs text-slate-500 block">Email tiếp nhận yêu cầu</span>
                      <a
                        href="mailto:compliance@example.gov.vn"
                        className="font-medium text-brand-600 hover:underline"
                      >
                        compliance@example.gov.vn
                      </a>
                    </div>
                  </div>

                  <div className="flex items-start gap-2.5">
                    <PhoneCall className="mt-0.5 size-4 text-emerald-600 shrink-0" />
                    <div>
                      <span className="text-xs text-slate-500 block">Hotline giải quyết khiếu nại</span>
                      <span className="font-semibold text-slate-900">1900 xxxx / 0239.xxx.xxxx</span>
                    </div>
                  </div>

                  <div className="flex items-start gap-2.5">
                    <Building2 className="mt-0.5 size-4 text-indigo-600 shrink-0" />
                    <div>
                      <span className="text-xs text-slate-500 block">Đơn vị chủ quản tiếp nhận</span>
                      <span className="text-slate-800">Bộ phận Quản trị An toàn thông tin</span>
                    </div>
                  </div>

                  <div className="flex items-start gap-2.5">
                    <Clock className="mt-0.5 size-4 text-amber-600 shrink-0" />
                    <div>
                      <span className="text-xs text-slate-500 block">Thời hạn xử lý phản hồi</span>
                      <span className="font-medium text-amber-800">Tối đa 72 giờ làm việc</span>
                    </div>
                  </div>
                </div>
              </Card>

              {/* Căn cứ pháp lý */}
              <Card title="Căn cứ pháp lý áp dụng">
                <ul className="space-y-2 text-xs text-slate-600">
                  <li className="flex items-start gap-2">
                    <Scale className="mt-0.5 size-3.5 text-slate-400 shrink-0" />
                    <span>
                      <strong>Nghị định 13/2023/NĐ-CP</strong> của Chính phủ về Bảo vệ dữ liệu cá nhân.
                    </span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Scale className="mt-0.5 size-3.5 text-slate-400 shrink-0" />
                    <span>
                      <strong>Luật An toàn thông tin mạng 2015</strong> và các văn bản hướng dẫn thi hành.
                    </span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Scale className="mt-0.5 size-3.5 text-slate-400 shrink-0" />
                    <span>
                      <strong>Luật An ninh mạng 2018</strong> về bảo vệ an ninh thông tin quốc gia.
                    </span>
                  </li>
                </ul>
              </Card>

              {/* Lịch sử phiên bản */}
              <Card title="Lịch sử các bản phát hành">
                <div className="space-y-2">
                  <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <History className="size-3.5 text-slate-400" />
                      <span className="font-semibold text-slate-700">Phiên bản 1.0</span>
                    </div>
                    <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                      Hiện hành
                    </Badge>
                  </div>
                  <p className="text-[11px] text-slate-400 leading-normal">
                    Khi hệ thống cập nhật phạm vi dữ liệu hoặc chính sách mới, thông báo tuân thủ phiên bản tiếp theo sẽ được phát hành và yêu cầu người dùng xác nhận lại.
                  </p>
                </div>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}