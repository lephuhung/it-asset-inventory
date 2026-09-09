/**
 * Front-end validators cho phone/email.
 *
 * - Server (FastAPI + Pydantic) là nguồn validate cuối cùng (`EmailStr` +
 *   `phone: str | None = Field(max_length=20)`). Client chỉ là UX-first guard
 *   để chặn sai format NGAY khi user nhập, tránh round-trip 422.
 * - Số điện thoại: chấp nhận đầu số di động VN hiện hành (03/05/07/08/09) —
 *   10 chữ số; tự chuẩn hoá "0…", "+84…", khoảng trắng/dot/dash về "0…".
 * - Email: regex chặt hơn HTML5 mặc định (yêu cầu TLD ≥ 2 ký tự, không
 *   cho phép khoảng trắng, phải có local-part + "@" + domain).
 */

/** Đầu số di động Việt Nam đang được cấp (quy hoạch của Bộ TT&TT). */
const PHONE_VN_MOBILE_PREFIX: Record<string, true> = {
  "03": true,
  "05": true,
  "07": true,
  "08": true,
  "09": true,
};

/**
 * Chuẩn hoá SĐT về dạng "0XXXXXXXXX" (10 chữ số, bắt đầu bằng 0).
 * - Bỏ hết ký tự không phải số.
 * - Nếu bắt đầu bằng "84" và còn 11 chữ số → thay "84" thành "0".
 * - Ngược lại giữ nguyên chuỗi số.
 */
export function normalizePhoneVN(raw: string | null | undefined): string {
  const digits = (raw ?? "").replace(/\D+/g, "");
  if (digits.length === 0) return "";
  if (digits.startsWith("84") && digits.length === 11) {
    return "0" + digits.slice(2);
  }
  return digits;
}

/**
 * Validate SĐT Việt Nam (di động).
 * Trả về "" nếu hợp lệ hoặc rỗng; trả về chuỗi thông báo lỗi tiếng Việt
 * nếu không hợp lệ. `required = true` → rỗng cũng là lỗi.
 */
export function validatePhoneVN(
  raw: string | null | undefined,
  opts: { required?: boolean } = {},
): string {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) return opts.required ? "Vui lòng nhập số điện thoại" : "";
  const normalized = normalizePhoneVN(trimmed);
  if (!/^[0-9]+$/.test(normalized)) {
    return "Số điện thoại chỉ gồm chữ số";
  }
  if (normalized.length !== 10) {
    return "Số điện thoại phải có đúng 10 chữ số";
  }
  if (!normalized.startsWith("0")) {
    return "Số điện thoại phải bắt đầu bằng 0";
  }
  if (!PHONE_VN_MOBILE_PREFIX[normalized.slice(0, 2)]) {
    return "Đầu số không hợp lệ (03/05/07/08/09)";
  }
  return "";
}

/** Validate email. Trả về "" nếu hợp lệ hoặc rỗng; ngược lại trả message. */
export function validateEmail(
  raw: string | null | undefined,
  opts: { required?: boolean } = {},
): string {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) return opts.required ? "Vui lòng nhập email" : "";
  // RFC-lite: local + "@" + domain + "." + TLD (≥2 ký tự chữ).
  // Không cho khoảng trắng; cho phép + . _ % - trong local-part.
  const re = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/;
  if (!re.test(trimmed)) return "Email không đúng định dạng";
  if (trimmed.length > 254) return "Email quá dài (tối đa 254 ký tự)";
  return "";
}
