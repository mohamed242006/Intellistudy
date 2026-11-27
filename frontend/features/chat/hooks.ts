"use client";

/** Chat server state (gates GF1-11..16, GF1-19). */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { nextOffset } from "@/features/courses/hooks";
import { ApiError } from "@/lib/api/errors";
import type { ConversationDetail, ConversationList, MessageOut } from "@/lib/api/types";
import { CONVERSATION_PAGE_SIZE, queryKeys } from "@/lib/query/keys";
import { createConversation, deleteConversation, getConversation, listConversations, sendMessage } from "./api";

export function useConversations(courseId: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useInfiniteQuery({
    queryKey: queryKeys.conversationList(courseId),
    queryFn: ({ pageParam, signal }) => listConversations(courseId, CONVERSATION_PAGE_SIZE, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    enabled,
  });
}

export function useConversation(conversationId: string | null) {
  return useQuery({
    queryKey: queryKeys.conversation(conversationId ?? ""),
    queryFn: ({ signal }) => getConversation(conversationId!, signal),
    enabled: conversationId !== null,
  });
}

export function useCreateConversation(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => createConversation(courseId),
    onSuccess: (conversation) => {
      client.setQueryData<ConversationDetail>(queryKeys.conversation(conversation.id), { ...conversation, messages: [] });
      void client.invalidateQueries({ queryKey: queryKeys.conversationsOf(courseId) });
    },
  });
}

/** Delete; a 404 means it is already gone. */
export function useDeleteConversation(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (conversationId: string) => {
      try {
        await deleteConversation(conversationId);
      } catch (error) {
        if (!(error instanceof ApiError && error.kind === "not_found")) throw error;
      }
      return conversationId;
    },
    onSuccess: (conversationId) => {
      client.setQueriesData<InfiniteData<ConversationList, number>>({ queryKey: queryKeys.conversationsOf(courseId) }, (data) =>
        data ? { ...data, pages: data.pages.map((p) => ({ ...p, items: p.items.filter((c) => c.id !== conversationId) })) } : data,
      );
      client.removeQueries({ queryKey: queryKeys.conversation(conversationId) });
      void client.invalidateQueries({ queryKey: queryKeys.conversationsOf(courseId) });
    },
  });
}

/**
 * Send one question. The stored exchange returned by the backend (201) is appended to this conversation's cache, with
 * its server id and time; nothing is shown as an answer before that. Never retried automatically.
 */
export function useSendMessage(courseId: string, conversationId: string, documentIds?: readonly string[]) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (question: string) => sendMessage(conversationId, question, documentIds),
    onSuccess: (message: MessageOut) => {
      client.setQueryData<ConversationDetail>(queryKeys.conversation(conversationId), (data) =>
        data && !data.messages.some((m) => m.id === message.id) ? { ...data, updated_at: message.created_at, messages: [...data.messages, message] } : data,
      );
      void client.invalidateQueries({ queryKey: queryKeys.conversationsOf(courseId) });
    },
  });
}
