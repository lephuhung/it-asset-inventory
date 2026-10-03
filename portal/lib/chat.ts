/**
 * Chat Assistant — HTTP wrappers.
 *
 * Mọi request đi qua BFF `/api/proxy` (buffering) — chỉ dùng cho CRUD hội thoại.
 * Luồng token KHÔNG dùng wrapper này: nó đi qua route SSE riêng
 * `POST /api/chat/stream` (xem `components/chat/use-chat-stream.ts`).
 */

import { api } from "@/lib/api";
import type {
  ChatConversation,
  ChatConversationDetail,
  ChatMachineContext,
} from "@/lib/types";

export interface ChatListParams {
  limit?: number;
  offset?: number;
  archived?: boolean;
}

export interface ChatConversationPatch {
  title?: string | null;
  /** `null` = gỡ ngữ cảnh máy đã lưu. */
  machine_id?: string | null;
}

export interface ChatCancelResult {
  status: string;
}

export const chatApi = {
  listConversations(params: ChatListParams = {}) {
    // Copy sang object phẳng để tương thích kiểu query của `api.get`.
    const query: Record<string, string | number | boolean | null | undefined> = { ...params };
    return api.get<{ items: ChatConversation[]; total: number }>("/chat/conversations", query);
  },

  getConversation(id: string) {
    return api.get<ChatConversationDetail>(`/chat/conversations/${encodeURIComponent(id)}`);
  },

  createConversation(body: { title?: string | null; machine_id?: string | null } = {}) {
    return api.post<ChatConversation>("/chat/conversations", body);
  },

  patchConversation(id: string, body: ChatConversationPatch) {
    return api.patch<ChatConversation>(`/chat/conversations/${encodeURIComponent(id)}`, body);
  },

  deleteConversation(id: string) {
    return api.delete<void>(`/chat/conversations/${encodeURIComponent(id)}`);
  },

  /** Dừng turn đang chạy. Server trả 409 nếu turn đã terminal. */
  cancelTurn(id: string, turnId: string) {
    return api.post<ChatCancelResult>(`/chat/conversations/${encodeURIComponent(id)}/cancel`, {
      turn_id: turnId,
    });
  },
};

export type {
  ChatConversation,
  ChatConversationDetail,
  ChatMachineContext,
  ChatSseEvent,
  ChatMessage,
  ChatRole,
  ChatToolCall,
  ChatTurn,
  ChatTurnStatus,
  ChatErrorCategory,
} from "@/lib/types";