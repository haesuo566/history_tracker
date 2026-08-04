"use client";

import { useEffect, useRef } from "react";

import type { ChatStatus } from "@/hooks/useChatSessions";

interface ChatInputProps {
  value: string;
  status: ChatStatus;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
}

const MAX_TEXTAREA_HEIGHT = 200;

export function ChatInput({ value, status, onChange, onSubmit, onStop }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isLoading = status === "loading";
  const canSubmit = !isLoading && value.trim().length > 0;

  // 입력 길이에 따라 높이를 늘리고, 한계에 닿으면 내부 스크롤로 넘긴다.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea === null) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`;
  }, [value]);

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    // 한글 등 IME 조합 중의 Enter 는 글자 확정용이므로 전송하지 않는다.
    if (event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (canSubmit) onSubmit();
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) onSubmit();
      }}
      className="mx-auto w-full max-w-3xl px-4 pb-4"
    >
      <div className="flex items-end gap-2 rounded-2xl border border-zinc-200 bg-white p-2 shadow-lg shadow-zinc-200/60 transition-shadow focus-within:border-blue-300 focus-within:ring-2 focus-within:ring-blue-100 dark:border-zinc-800 dark:bg-zinc-900 dark:shadow-none dark:focus-within:border-blue-800 dark:focus-within:ring-blue-950/40">
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="찾고 싶은 페이지를 설명해 주세요… (Shift+Enter 로 줄바꿈)"
          aria-label="메시지 입력"
          className="max-h-[200px] flex-1 resize-none bg-transparent px-2 py-2 text-[15px] leading-relaxed outline-none placeholder:text-zinc-400 dark:placeholder:text-zinc-500"
        />

        {isLoading ? (
          <button
            type="button"
            onClick={onStop}
            className="shrink-0 rounded-xl bg-zinc-800 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-white"
          >
            중단
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSubmit}
            className="shrink-0 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-blue-600/25 transition-all hover:shadow-md hover:shadow-blue-600/35 hover:brightness-110 active:brightness-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none disabled:hover:brightness-100"
          >
            보내기
          </button>
        )}
      </div>

      <p className="mt-2 text-center text-xs text-zinc-400 dark:text-zinc-500">
        가장 관련 있어 보이는 기록 한 건을 보여 줍니다.
      </p>
    </form>
  );
}
