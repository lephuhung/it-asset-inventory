"use client";

import { useMemo } from "react";
import type { Organization } from "@/lib/types";
import { flattenOrgTree } from "@/lib/format";

/**
 * Trả về cây tổ chức đã được làm phẳng (kèm độ sâu) — memoized theo `orgs`.
 *
 * Trước đây mỗi lần render lại gọi `flattenOrgTree(orgs)` trực tiếp trong JSX
 * (machines/inventory-stats/users/api-keys/reports/notifications-alerts) — không
 * chỉ tốn O(n) lặp lại mà còn tạo mảng mới khiến child consumers (`<Select>`,
 * `orgName()` lookup) thấy prop mới và remount/recompute. Memo giúp giữ tham
 * chiếu ổn định khi `orgs` không đổi.
 */
export function useFlatOrgs(orgs: Organization[]): Array<{
  org: Organization;
  depth: number;
}> {
  return useMemo(() => flattenOrgTree(orgs), [orgs]);
}
