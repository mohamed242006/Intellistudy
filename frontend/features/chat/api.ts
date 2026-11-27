/** Chat endpoints (backend/app/api/v1/chat.py). Ids go in the path only, URL-encoded. */
import { apiRequest, query } from "@/lib/api/client";
import type { ConversationDetail, ConversationList, ConversationOut, MessageOut } from "@/lib/api/types";

const conv = (id: string) => `/conversations/${encodeURIComponent(id)}`;

export function listConversations(courseId: string, limit: number, offset: number, signal?: AbortSignal): Promise<ConversationList> {
  return apiRequest<ConversationList>(`/courses/${encodeURIComponent(courseId)}/conversations${query({ limit, offset })}`, { signal });
}

/** No title: the backend names it "New conversation"; the frontend never invents a title. */
export function createConversation(courseId: string): Promise<ConversationOut> {
  return apiRequest<ConversationOut>(`/courses/${encodeURIComponent(courseId)}/conversations`, { method: "POST", body: {} });
}

export function getConversation(id: string, signal?: AbortSignal): Promise<ConversationDetail> {
  return apiRequest<ConversationDetail>(conv(id), { signal });
}

export function deleteConversation(id: string): Promise<void> {
  return apiRequest<void>(conv(id), { method: "DELETE" });
}

/** Synchronous: 201 with the stored exchange (question + answer). */
/** `documentIds` narrows retrieval to those ready files of the course (MessageCreate.document_ids); omitted = all. */
export function sendMessage(id: string, question: string, documentIds?: readonly string[]): Promise<MessageOut> {
  const body = documentIds && documentIds.length ? { question, document_ids: [...new Set(documentIds)] } : { question };
  return apiRequest<MessageOut>(`${conv(id)}/messages`, { method: "POST", body });
}
