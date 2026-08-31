"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { localNowIso } from "@/lib/clock";
import type {
  ChatMessage,
  ChatRequestBody,
  ChatResponseBody,
  ConversationDetailBody,
  ConversationListBody,
  ErrorBody,
  SearchResult,
} from "@/lib/types";

export type ChatStatus = "idle" | "loading";

/**
 * 사이드바에 표시되는 대화 세션.
 * conversationId 가 없으면 아직 백엔드에 저장되지 않은 새 대화(첫 메시지를 보내야 생긴다)다.
 * loaded 가 false 면 목록 조회로만 알고 있는 세션이라, 고르는 시점에 메시지를 따로 불러와야 한다.
 */
export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  loaded: boolean;
  status: ChatStatus;
  error: string | null;
}

const NEW_SESSION_TITLE = "새 대화";
const TITLE_MAX_LENGTH = 30;

function createId(): string {
  return crypto.randomUUID();
}

function createEmptySession(): ChatSession {
  return { id: createId(), title: NEW_SESSION_TITLE, messages: [], loaded: true, status: "idle", error: null };
}

/** 첫 사용자 메시지로 세션 제목을 만든다. 목록에서 너무 길게 늘어지지 않도록 잘라낸다. */
function deriveTitle(text: string): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > TITLE_MAX_LENGTH
    ? `${collapsed.slice(0, TITLE_MAX_LENGTH)}…`
    : collapsed;
}

/**
 * 백엔드에 저장된 과거 메시지를 화면 말풍선 형태로 바꾼다.
 * role 과 results 는 /api/conversations/{id} 단계(backend.ts)에서 이미 형태가 걸러졌다.
 */
function toChatMessage(raw: { role: string; content: string; results: SearchResult[] }): ChatMessage {
  return raw.role === "user"
    ? { id: createId(), role: "user", content: raw.content }
    : {
        id: createId(),
        role: "assistant",
        results: raw.results,
        answer: raw.content.length > 0 ? raw.content : null,
      };
}

export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => [createEmptySession()]);
  const [activeSessionId, setActiveSessionId] = useState(() => sessions[0].id);
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  // 진행 중인 요청과 각 세션이 이어가는 백엔드 대화 id. 렌더링에 쓰이지 않으므로 ref 로 둔다.
  const abortsRef = useRef(new Map<string, AbortController>());
  const conversationIdsRef = useRef(new Map<string, string>());

  // isLoadingSessions/sessionsError 초기값이 이미 true/null 이므로, 마운트 시 호출은 그 값을
  // 그대로 쓰면 된다. 재시도 버튼처럼 상태를 다시 로딩중으로 되돌려야 하는 경우만 별도로 처리한다.
  const fetchSessions = useCallback((signal: AbortSignal) => {
    fetch("/api/conversations", { signal })
      .then(async (response) => {
        if (!response.ok) {
          const detail = await response
            .json()
            .then((payload: ErrorBody) => payload.message)
            .catch(() => null);
          throw new Error(detail ?? `대화 목록을 불러오지 못했습니다 (${response.status}).`);
        }
        return (await response.json()) as ConversationListBody;
      })
      .then(({ conversations }) => {
        const fetched = conversations.map((conversation) => {
          const id = createId();
          conversationIdsRef.current.set(id, conversation.conversation_id);
          return {
            id,
            title: conversation.title ?? NEW_SESSION_TITLE,
            messages: [],
            loaded: false,
            status: "idle" as ChatStatus,
            error: null,
          };
        });
        // 로딩 중 사용자가 이미 시작한 draft(아직 백엔드에 없는 세션)는 그대로 두고 뒤에 이어붙인다.
        setSessions((previous) => [...previous, ...fetched]);
      })
      .catch((caught) => {
        if (caught instanceof Error && caught.name === "AbortError") return;
        setSessionsError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
      })
      .finally(() => {
        setIsLoadingSessions(false);
      });
  }, []);

  // 최초 진입 시 한 번만 대화 목록을 불러온다.
  useEffect(() => {
    const controller = new AbortController();
    fetchSessions(controller.signal);
    return () => controller.abort();
  }, [fetchSessions]);

  const retryLoadSessions = useCallback(() => {
    setIsLoadingSessions(true);
    setSessionsError(null);
    fetchSessions(new AbortController().signal);
  }, [fetchSessions]);

  // 아직 메시지를 하나도 보내지 않은(=백엔드 conversation 이 없는) 빈 대화는 동시에 하나만 둔다.
  // 목록 조회로만 알고 있는 세션(loaded=false)도 메시지 배열이 비어 있지만, conversationIdsRef 에
  // 매핑이 있으므로 draft 로 오인하지 않는다.
  const createSession = useCallback(() => {
    setSessions((previous) => {
      const existingDraft = previous.find(
        (session) => session.messages.length === 0 && !conversationIdsRef.current.has(session.id),
      );
      if (existingDraft !== undefined) {
        setActiveSessionId(existingDraft.id);
        return previous;
      }
      const fresh = createEmptySession();
      setActiveSessionId(fresh.id);
      return [fresh, ...previous];
    });
  }, []);

  /** 목록 조회로만 알고 있던 세션을 고르면, 이때 처음으로 메시지 전문을 불러온다. */
  const hydrateSession = useCallback((id: string) => {
    const conversationId = conversationIdsRef.current.get(id);
    if (conversationId === undefined) return;

    setSessions((previous) =>
      previous.map((session) => (session.id === id ? { ...session, status: "loading" } : session)),
    );

    fetch(`/api/conversations/${conversationId}`)
      .then(async (response) => {
        if (!response.ok) {
          const detail = await response
            .json()
            .then((payload: ErrorBody) => payload.message)
            .catch(() => null);
          throw new Error(detail ?? `대화를 불러오지 못했습니다 (${response.status}).`);
        }
        return (await response.json()) as ConversationDetailBody;
      })
      .then(({ messages }) => {
        setSessions((previous) =>
          previous.map((session) =>
            session.id === id
              ? { ...session, messages: messages.map(toChatMessage), loaded: true, status: "idle" }
              : session,
          ),
        );
      })
      .catch((caught) => {
        const message = caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.";
        setSessions((previous) =>
          previous.map((session) => (session.id === id ? { ...session, status: "idle", error: message } : session)),
        );
      });
  }, []);

  const selectSession = useCallback(
    (id: string) => {
      setActiveSessionId(id);
      const session = sessions.find((candidate) => candidate.id === id);
      if (session !== undefined && !session.loaded) hydrateSession(id);
    },
    [sessions, hydrateSession],
  );

  const renameSession = useCallback((id: string, rawTitle: string) => {
    const title = rawTitle.trim();
    if (title.length === 0) return;

    setSessions((previous) =>
      previous.map((session) => (session.id === id ? { ...session, title } : session)),
    );

    const conversationId = conversationIdsRef.current.get(id);
    // 아직 첫 메시지를 보내지 않은 draft 는 백엔드에 없으므로 로컬 상태만 바꾸면 된다.
    if (conversationId === undefined) return;

    fetch(`/api/conversations/${conversationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).catch((caught) => {
      console.error("[useChatSessions] failed to rename conversation", conversationId, caught);
    });
  }, []);

  const deleteSession = useCallback(
    (id: string) => {
      abortsRef.current.get(id)?.abort();
      abortsRef.current.delete(id);
      const conversationId = conversationIdsRef.current.get(id);
      conversationIdsRef.current.delete(id);

      const remaining = sessions.filter((session) => session.id !== id);
      const next = remaining.length > 0 ? remaining : [createEmptySession()];
      setSessions(next);
      if (activeSessionId === id) setActiveSessionId(next[0].id);

      // 아직 첫 메시지를 보내지 않은 draft 는 백엔드에 존재하지 않으므로 지울 것이 없다.
      if (conversationId === undefined) return;
      fetch(`/api/conversations/${conversationId}`, { method: "DELETE" }).catch((caught) => {
        console.error("[useChatSessions] failed to delete conversation", conversationId, caught);
      });
    },
    [sessions, activeSessionId],
  );

  const stop = useCallback((sessionId: string) => {
    abortsRef.current.get(sessionId)?.abort();
    abortsRef.current.delete(sessionId);
    setSessions((previous) =>
      previous.map((session) => (session.id === sessionId ? { ...session, status: "idle" } : session)),
    );
  }, []);

  const send = useCallback(async (sessionId: string, input: string) => {
    const text = input.trim();
    if (text.length === 0 || abortsRef.current.has(sessionId)) return;

    setSessions((previous) =>
      previous.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              title: session.messages.length === 0 ? deriveTitle(text) : session.title,
              messages: [...session.messages, { id: createId(), role: "user", content: text }],
              status: "loading",
              error: null,
            }
          : session,
      ),
    );

    const controller = new AbortController();
    abortsRef.current.set(sessionId, controller);

    try {
      const requestBody: ChatRequestBody = {
        message: text,
        conversation_id: conversationIdsRef.current.get(sessionId) ?? null,
        // "어제 본 글"의 하루 경계는 이 사람의 자정이다. 라우트 핸들러는 서버에서 돌아 브라우저의
        // 시간대를 알 수 없으므로 여기서 실어 보낸다.
        client_now: localNowIso(),
      };
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });

      if (!response.ok) {
        const detail = await response
          .json()
          .then((payload: ErrorBody) => payload.message)
          .catch(() => null);
        throw new Error(detail ?? `요청이 실패했습니다 (${response.status}).`);
      }

      const { conversation_id, results, answer } = (await response.json()) as ChatResponseBody;

      // 응답을 기다리는 사이 stop() 이나 삭제로 이 요청이 무효화됐으면 되살리지 않는다.
      if (abortsRef.current.get(sessionId) !== controller) return;

      conversationIdsRef.current.set(sessionId, conversation_id);
      setSessions((previous) =>
        previous.map((session) =>
          session.id === sessionId
            ? {
                ...session,
                messages: [...session.messages, { id: createId(), role: "assistant", results, answer }],
              }
            : session,
        ),
      );
    } catch (caught) {
      // 중단은 오류가 아니다. 응답 말풍선을 추가하지 않고 그대로 끝낸다.
      if (caught instanceof Error && caught.name === "AbortError") return;
      const message = caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.";
      setSessions((previous) =>
        previous.map((session) => (session.id === sessionId ? { ...session, error: message } : session)),
      );
    } finally {
      abortsRef.current.delete(sessionId);
      setSessions((previous) =>
        previous.map((session) => (session.id === sessionId ? { ...session, status: "idle" } : session)),
      );
    }
  }, []);

  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? sessions[0];

  const sendActive = useCallback((text: string) => send(activeSessionId, text), [send, activeSessionId]);
  const stopActive = useCallback(() => stop(activeSessionId), [stop, activeSessionId]);

  return {
    sessions,
    activeSessionId,
    isLoadingSessions,
    sessionsError,
    retryLoadSessions,
    createSession,
    selectSession,
    renameSession,
    deleteSession,
    messages: activeSession.messages,
    status: activeSession.status,
    error: activeSession.error,
    send: sendActive,
    stop: stopActive,
  };
}
