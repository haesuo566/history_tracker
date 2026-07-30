"use client";

import type { BatchStatus } from "@/hooks/useBatch";
import type { BatchSummary } from "@/lib/types";

/** 아직 확정되지 않은 이름. 바꿀 때 이 한 곳만 고치면 된다. */
export const BATCH_LABEL = "학습";

function Spinner() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5 animate-spin">
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeOpacity="0.25"
      />
      <path
        d="M8 2a6 6 0 0 1 6 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

interface BatchButtonProps {
  status: BatchStatus;
  onRun: () => void;
}

export function BatchButton({ status, onRun }: BatchButtonProps) {
  const isRunning = status === "running";

  return (
    <button
      type="button"
      onClick={onRun}
      disabled={isRunning}
      aria-busy={isRunning}
      className="flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
    >
      {isRunning && <Spinner />}
      {isRunning ? `${BATCH_LABEL} 중…` : BATCH_LABEL}
    </button>
  );
}

function Stat({ label, value, muted }: { label: string; value: number; muted?: boolean }) {
  return (
    <span className={muted === true ? "text-zinc-500 dark:text-zinc-400" : undefined}>
      {label} <span className="font-semibold tabular-nums">{value}</span>
    </span>
  );
}

interface BatchResultProps {
  summary: BatchSummary;
  onDismiss: () => void;
}

export function BatchResult({ summary, onDismiss }: BatchResultProps) {
  const { attempted, succeeded, failed } = summary;
  const hasFailure = failed > 0;

  return (
    <div
      role="status"
      aria-live="polite"
      className={`mx-auto mt-2 w-full max-w-3xl px-4 text-sm ${
        hasFailure ? "text-amber-700 dark:text-amber-300" : "text-zinc-700 dark:text-zinc-300"
      }`}
    >
      <div
        className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${
          hasFailure
            ? "border-amber-200 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/30"
            : "border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/60"
        }`}
      >
        {attempted === 0 ? (
          <span className="flex-1">{BATCH_LABEL}할 새 문서가 없습니다.</span>
        ) : (
          <span className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-medium">{BATCH_LABEL} 완료</span>
            <Stat label="시도" value={attempted} />
            <Stat label="성공" value={succeeded} />
            <Stat label="실패" value={failed} muted={!hasFailure} />
          </span>
        )}

        <button
          type="button"
          onClick={onDismiss}
          aria-label="닫기"
          className="shrink-0 rounded-md px-1.5 text-base leading-none text-zinc-400 transition-colors hover:text-zinc-600 dark:hover:text-zinc-200"
        >
          ×
        </button>
      </div>
    </div>
  );
}
