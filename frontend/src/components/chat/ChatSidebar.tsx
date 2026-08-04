"use client";

import type { ChatSession } from "@/hooks/useChatSessions";

interface ChatSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string;
  isOpen: boolean;
  isLoadingSessions: boolean;
  sessionsError: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
  onRetry: () => void;
}

function LogoMark() {
  return (
    <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-indigo-600 shadow-sm shadow-blue-600/30">
      <svg aria-hidden viewBox="0 0 16 16" className="size-3.5 text-white">
        <circle cx="6.8" cy="6.8" r="4.3" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M10.2 10.2 14 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    </div>
  );
}

function CollapseIcon() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-4">
      <rect x="1.5" y="2.5" width="13" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M6 2.5v11" stroke="currentColor" strokeWidth="1.3" />
      <path d="M4 6.3 2 8l2 1.7" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-4">
      <path
        d="M8 2.5v11M2.5 8h11"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5">
      <path
        d="M3 4.5h10M6.5 4.5V3a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v1.5M4.5 4.5 5 13a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1l.5-8.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ChatSidebar({
  sessions,
  activeSessionId,
  isOpen,
  isLoadingSessions,
  sessionsError,
  onSelect,
  onCreate,
  onDelete,
  onClose,
  onRetry,
}: ChatSidebarProps) {
  return (
    <>
      {isOpen && (
        <div
          aria-hidden
          onClick={onClose}
          className="fixed inset-0 z-30 bg-black/40 backdrop-blur-[1px] md:hidden"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 w-72 shrink-0 overflow-hidden border-r border-zinc-200/80 bg-zinc-50 shadow-xl transition-[transform,width] duration-300 ease-in-out md:static md:shadow-none dark:border-zinc-800/80 dark:bg-zinc-950 ${
          isOpen ? "translate-x-0 md:w-72" : "-translate-x-full md:w-0"
        }`}
      >
        <div className="flex h-full w-72 flex-col">
          <div className="flex items-center gap-2 px-3 pt-3 pb-1">
            <LogoMark />
            <span className="flex-1 truncate text-sm font-semibold tracking-tight text-zinc-800 dark:text-zinc-100">
              검색 기록 찾기
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="사이드바 접기"
              className="shrink-0 rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-zinc-200/70 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            >
              <CollapseIcon />
            </button>
          </div>

          <div className="p-3 pt-2">
            <button
              type="button"
              onClick={onCreate}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm shadow-blue-600/25 transition-all hover:shadow-md hover:shadow-blue-600/35 hover:brightness-110 active:brightness-95"
            >
              <PlusIcon />
              새 대화
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto px-2 pb-3">
            {isLoadingSessions && (
              <ul className="space-y-0.5 px-1 py-1" aria-hidden>
                {[0, 1, 2].map((key) => (
                  <li key={key} className="h-9 animate-pulse rounded-lg bg-zinc-200/70 dark:bg-zinc-800/60" />
                ))}
              </ul>
            )}

            {!isLoadingSessions && sessionsError !== null && (
              <div className="mx-1 mt-1 space-y-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-600 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-400">
                <p>{sessionsError}</p>
                <button
                  type="button"
                  onClick={onRetry}
                  className="font-medium underline decoration-red-300 underline-offset-2 hover:decoration-red-500"
                >
                  다시 시도
                </button>
              </div>
            )}

            <ul className="space-y-0.5">
              {!isLoadingSessions && sessions.map((session) => {
                const isActive = session.id === activeSessionId;
                return (
                  <li key={session.id} className="group relative">
                    <button
                      type="button"
                      onClick={() => onSelect(session.id)}
                      aria-current={isActive}
                      className={`flex w-full items-center gap-2 rounded-lg border-l-2 px-3 py-2 pr-8 text-left text-sm transition-colors ${
                        isActive
                          ? "border-blue-600 bg-white text-zinc-900 shadow-sm dark:bg-zinc-800/90 dark:text-zinc-100"
                          : "border-transparent text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-900/60"
                      }`}
                    >
                      {session.status === "loading" && (
                        <span
                          aria-hidden
                          className="size-1.5 shrink-0 animate-pulse rounded-full bg-blue-500"
                        />
                      )}
                      <span className="truncate">{session.title}</span>
                    </button>

                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onDelete(session.id);
                      }}
                      aria-label={`${session.title} 대화 삭제`}
                      className="absolute inset-y-0 right-1 flex items-center rounded-md px-1.5 text-zinc-400 opacity-0 transition-opacity group-hover:opacity-100 hover:text-red-500 focus-visible:opacity-100 dark:hover:text-red-400"
                    >
                      <TrashIcon />
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>
      </aside>
    </>
  );
}
