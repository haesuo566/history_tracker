"use client";

import { useState } from "react";

import { BatchButton, BatchResult } from "@/components/chat/BatchControl";
import { ChatInput } from "@/components/chat/ChatInput";
import { MessageList } from "@/components/chat/MessageList";
import { useBatch } from "@/hooks/useBatch";
import { useChat } from "@/hooks/useChat";

export function ChatContainer() {
  const { messages, status, error, send, stop, reset } = useChat();
  const batch = useBatch();
  const [input, setInput] = useState("");

  function handleSubmit() {
    const text = input;
    setInput("");
    void send(text);
  }

  function handleReset() {
    reset();
    setInput("");
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h1 className="text-sm font-semibold tracking-tight">검색 기록 찾기</h1>
        <div className="flex items-center gap-2">
          <BatchButton status={batch.status} onRun={() => void batch.run()} />
          <button
            type="button"
            onClick={handleReset}
            disabled={messages.length === 0}
            className="rounded-lg border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
          >
            새 대화
          </button>
        </div>
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
  );
}
