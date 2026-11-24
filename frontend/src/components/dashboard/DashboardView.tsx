"use client";

import { useState } from "react";

import { BarList, ColumnChart, DataTable, DonutChart, LineChart, formatValue } from "@/components/dashboard/charts";
import type { Dashboard, DashboardPanel } from "@/lib/types";

/** 이름이 긴 범주라 가로 막대로 그리는 기준. 나머지(날짜·요일·시간대)는 세로 막대다. */
const HORIZONTAL_DIMENSIONS = new Set(["site"]);

function KpiTile({ panel }: { panel: DashboardPanel }) {
  const point = panel.points[0];
  return (
    <div className="rounded-xl bg-[color:var(--viz-surface)] px-4 py-3 ring-1 ring-zinc-200/70 dark:ring-zinc-700/60">
      <p className="truncate text-xs text-[color:var(--viz-ink-2)]" title={panel.title}>
        {panel.title}
      </p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-[color:var(--viz-ink)]">
        {point === undefined ? "–" : formatValue(point.value, panel.unit)}
      </p>
    </div>
  );
}

function PanelBody({ panel }: { panel: DashboardPanel }) {
  const { points, unit } = panel;
  switch (panel.chart) {
    case "line":
      return <LineChart points={points} unit={unit} />;
    case "pie":
      return <DonutChart points={points} unit={unit} />;
    case "table":
      return (
        <DataTable
          points={points}
          unit={unit}
          dimensionLabel={panel.dimensionLabel ?? ""}
          measureLabel={panel.measureLabel}
        />
      );
    default:
      return panel.dimension !== null && HORIZONTAL_DIMENSIONS.has(panel.dimension) ? (
        <BarList points={points} unit={unit} />
      ) : (
        <ColumnChart points={points} unit={unit} />
      );
  }
}

/**
 * 차트 패널 하나. 모든 차트는 표로도 볼 수 있다 — 색과 모양만으로 값을 읽게 하지 않으려는 것이고,
 * 화면 낭독기에는 차트 대신 표가 읽힌다(SVG 는 aria-hidden).
 */
function ChartPanel({ panel }: { panel: DashboardPanel }) {
  const [asTable, setAsTable] = useState(false);
  const canToggle = panel.chart !== "table" && panel.points.length > 0;
  const table = (
    <DataTable
      points={panel.points}
      unit={panel.unit}
      dimensionLabel={panel.dimensionLabel ?? ""}
      measureLabel={panel.measureLabel}
    />
  );

  return (
    <section className="rounded-xl bg-[color:var(--viz-surface)] px-4 py-3 ring-1 ring-zinc-200/70 dark:ring-zinc-700/60">
      <header className="mb-2 flex items-center gap-2">
        <h4 className="min-w-0 flex-1 truncate text-sm font-medium text-[color:var(--viz-ink)]">{panel.title}</h4>
        {canToggle && (
          <button
            type="button"
            onClick={() => setAsTable((previous) => !previous)}
            aria-pressed={asTable}
            className="shrink-0 rounded-md px-2 py-0.5 text-xs text-[color:var(--viz-ink-2)] transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            {asTable ? "차트로 보기" : "표로 보기"}
          </button>
        )}
      </header>
      {panel.points.length === 0 ? (
        <p className="py-6 text-center text-xs text-[color:var(--viz-muted)]">이 조건에 해당하는 기록이 없습니다.</p>
      ) : asTable ? (
        table
      ) : (
        <>
          <PanelBody panel={panel} />
          {panel.chart !== "table" && <div className="sr-only">{table}</div>}
        </>
      )}
    </section>
  );
}

/**
 * 대시보드 턴의 본문. 기간과 조건을 제목 바로 아래 적는다 — 차트만 보고는 어느 범위를 센 것인지
 * 알 수 없다. 숫자 하나짜리 패널은 앞에 한 줄로 모으고, 차트 패널은 그 아래 차례로 놓는다.
 */
export function DashboardView({ dashboard }: { dashboard: Dashboard }) {
  const kpis = dashboard.panels.filter((panel) => panel.chart === "kpi");
  const charts = dashboard.panels.filter((panel) => panel.chart !== "kpi");

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <h3 className="font-semibold tracking-tight">{dashboard.title}</h3>
        <div className="flex flex-wrap gap-1.5 text-xs">
          {[dashboard.period, ...dashboard.filters].map((condition) => (
            <span
              key={condition}
              className="rounded-full bg-zinc-100 px-2 py-0.5 text-zinc-600 dark:bg-zinc-700/60 dark:text-zinc-300"
            >
              {condition}
            </span>
          ))}
        </div>
      </div>

      {kpis.length > 0 && (
        <div className={`grid gap-2 ${kpis.length > 1 ? "sm:grid-cols-2" : ""} ${kpis.length > 2 ? "lg:grid-cols-3" : ""}`}>
          {kpis.map((panel, index) => (
            <KpiTile key={`${index}-${panel.title}`} panel={panel} />
          ))}
        </div>
      )}

      {charts.map((panel, index) => (
        <ChartPanel key={`${index}-${panel.title}`} panel={panel} />
      ))}

      {dashboard.notes.length > 0 && (
        <ul className="space-y-0.5 text-xs text-zinc-500 dark:text-zinc-400">
          {dashboard.notes.map((note) => (
            <li key={note}>※ {note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
