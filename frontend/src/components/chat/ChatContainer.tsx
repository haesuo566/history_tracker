"use client";

import { useState } from "react";

import { BatchButton, BatchResult } from "@/components/chat/BatchControl";
import { ChatInput } from "@/components/chat/ChatInput";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { MessageList } from "@/components/chat/MessageList";
import { useBatch } from "@/hooks/useBatch";
import { useChatSessions } from "@/hooks/useChatSessions";

function SidebarOpenIcon() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-4">
      <rect x="1.5" y="2.5" width="13" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M6 2.5v11" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3 6.3 5 8l-2 1.7" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ChatContainer() {
  const {
    sessions,
    activeSessionId,
    isLoadingSessions,
    sessionsError,
    retryLoadSessions,
    createSession,
    selectSession,
    renameSession,
    deleteSession,
    messages,
    status,
    error,
    send,
    stop,
  } = useChatSessions();
  const batch = useBatch();
  const [input, setInput] = useState("");
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const activeTitle = sessions.find((session) => session.id === activeSessionId)?.title ?? "새 대화";

  function handleSubmit() {
    const text = input;
    setInput("");
    void send(text);
  }

  // 사이드바는 모바일에서는 화면을 덮는 오버레이라 선택 후 닫아야 하지만,
  // 데스크톱(md 이상)에서는 항상 보이는 패널이므로 열린 상태를 유지한다.
  function isMobileViewport() {
    return window.matchMedia("(max-width: 767px)").matches;
  }

  function selectAndClose(id: string) {
    selectSession(id);
    if (isMobileViewport()) setIsSidebarOpen(false);
  }

  function createAndClose() {
    createSession();
    if (isMobileViewport()) setIsSidebarOpen(false);
    setInput("");
  }

  return (
    <div className="flex min-h-0 flex-1 bg-zinc-50 dark:bg-zinc-950">
      <ChatSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        isOpen={isSidebarOpen}
        isLoadingSessions={isLoadingSessions}
        sessionsError={sessionsError}
        onSelect={selectAndClose}
        onCreate={createAndClose}
        onRename={renameSession}
        onDelete={deleteSession}
        onClose={() => setIsSidebarOpen(false)}
        onRetry={retryLoadSessions}
      />

      <div className="flex min-h-0 flex-1 flex-col bg-white dark:bg-zinc-900">
        <header className="flex items-center gap-3 border-b border-zinc-200/80 bg-white/80 px-4 py-3 backdrop-blur-sm dark:border-zinc-800/80 dark:bg-zinc-900/80">
          {!isSidebarOpen && (
            <button
              type="button"
              onClick={() => setIsSidebarOpen(true)}
              aria-label="사이드바 펼치기"
              className="shrink-0 rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              <SidebarOpenIcon />
            </button>
          )}
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold tracking-tight text-zinc-800 dark:text-zinc-100">
              {activeTitle}
            </h1>
          </div>
          {status === "loading" && (
            <span className="hidden shrink-0 items-center gap-1.5 text-xs text-zinc-400 sm:flex dark:text-zinc-500">
              <span className="size-1.5 animate-pulse rounded-full bg-blue-500" />
              검색 중
            </span>
          )}
          <BatchButton status={batch.status} onRun={() => void batch.run()} />
        </header>

        {batch.summary !== null && (
          <BatchResult summary={batch.summary} onDismiss={batch.dismiss} />
        )}

        {batch.error !== null && (
          <div
            role="alert"
            className="mx-auto mt-2 w-full max-w-3xl px-4 text-sm text-red-600 dark:text-red-400"
          >
            <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900/50 dark:bg-red-950/40">
              <span className="flex-1">{batch.error}</span>
              <button
                type="button"
                onClick={batch.dismiss}
                aria-label="닫기"
                className="shrink-0 rounded-md px-1.5 text-base leading-none opacity-60 transition-opacity hover:opacity-100"
              >
                ×
              </button>
            </div>
          </div>
        )}

        <MessageList messages={messages} status={status} onPickSuggestion={setInput} />

        {error !== null && (
          <div
            role="alert"
            className="mx-auto mb-2 w-full max-w-3xl px-4 text-sm text-red-600 dark:text-red-400"
          >
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900/50 dark:bg-red-950/40">
              {error}
            </div>
          </div>
        )}

        <ChatInput
          value={input}
          status={status}
          onChange={setInput}
          onSubmit={handleSubmit}
          onStop={stop}
        />
      </div>
    </div>
  );
}
