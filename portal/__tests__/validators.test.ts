import { describe, expect, it } from "vitest";
import { normalizePhoneVN, validateEmail, validatePhoneVN } from "@/lib/validators";

describe("normalizePhoneVN", () => {
  it("strips spaces, dots, dashes, parentheses", () => {
    expect(normalizePhoneVN("0983 123 456")).toBe("0983123456");
    expect(normalizePhoneVN("0983.123.456")).toBe("0983123456");
    expect(normalizePhoneVN("0983-123-456")).toBe("0983123456");
    expect(normalizePhoneVN("(0983) 123 456")).toBe("0983123456");
  });

  it("converts +84 prefix to 0", () => {
    expect(normalizePhoneVN("+84 983 123 456")).toBe("0983123456");
    expect(normalizePhoneVN("84983123456")).toBe("0983123456");
  });

  it("returns empty for empty input", () => {
    expect(normalizePhoneVN("")).toBe("");
    expect(normalizePhoneVN(null)).toBe("");
    expect(normalizePhoneVN(undefined)).toBe("");
  });
});

describe("validatePhoneVN", () => {
  it("accepts all valid VN mobile prefixes", () => {
    expect(validatePhoneVN("0321234567")).toBe("");
    expect(validatePhoneVN("0521234567")).toBe("");
    expect(validatePhoneVN("0721234567")).toBe("");
    expect(validatePhoneVN("0821234567")).toBe("");
    expect(validatePhoneVN("0921234567")).toBe("");
    expect(validatePhoneVN("+84 983 123 456")).toBe("");
  });

  it("rejects when empty and required", () => {
    expect(validatePhoneVN("", { required: true })).toBe(
      "Vui lòng nhập số điện thoại",
    );
  });

  it("returns no error when empty and not required", () => {
    expect(validatePhoneVN("")).toBe("");
    expect(validatePhoneVN("   ")).toBe("");
  });

  it("rejects non-digits", () => {
    expect(validatePhoneVN("abc")).toBe("Số điện thoại chỉ gồm chữ số");
  });

  it("rejects wrong length", () => {
    expect(validatePhoneVN("098312345")).toBe("Số điện thoại phải có đúng 10 chữ số"); // 9
    expect(validatePhoneVN("09831234567")).toBe("Số điện thoại phải có đúng 10 chữ số"); // 11
  });

  it("rejects when does not start with 0", () => {
    expect(validatePhoneVN("1983123456")).toBe("Số điện thoại phải bắt đầu bằng 0");
  });

  it("rejects invalid mobile prefix", () => {
    expect(validatePhoneVN("0021234567")).toBe("Đầu số không hợp lệ (03/05/07/08/09)");
    expect(validatePhoneVN("0621234567")).toBe("Đầu số không hợp lệ (03/05/07/08/09)");
  });
});

describe("validateEmail", () => {
  it("accepts standard emails", () => {
    expect(validateEmail("a@example.gov.vn")).toBe("");
    expect(validateEmail("user.name+tag@sub.example.co")).toBe("");
  });

  it("returns no error when empty and not required", () => {
    expect(validateEmail("")).toBe("");
    expect(validateEmail(null)).toBe("");
  });

  it("rejects when empty and required", () => {
    expect(validateEmail("", { required: true })).toBe("Vui lòng nhập email");
  });

  it("rejects malformed emails", () => {
    expect(validateEmail("plainstring")).toBe("Email không đúng định dạng");
    expect(validateEmail("a@b")).toBe("Email không đúng định dạng");
    expect(validateEmail("a@b.c")).toBe("Email không đúng định dạng"); // TLD < 2
    expect(validateEmail("@example.com")).toBe("Email không đúng định dạng");
    expect(validateEmail("a@ example.com")).toBe("Email không đúng định dạng");
  });

  it("rejects too long", () => {
    const local = "a".repeat(250);
    const longEmail = `${local}@b.co`;
    expect(validateEmail(longEmail)).toBe("Email quá dài (tối đa 254 ký tự)");
  });
});
