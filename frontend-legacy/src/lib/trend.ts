import type { XhsTrendInfo } from "../types";

/** Compact arrow for a hot-topic trend, e.g. "↑12.3%" / "↓4.1%" / "→". */
export function formatTrend(trend?: XhsTrendInfo): string {
  if (!trend || trend.direction === "new" || !trend.days) return "";
  const delta = Math.abs(trend.delta_pct);
  if (trend.direction === "up") return `↑${delta}%`;
  if (trend.direction === "down") return `↓${delta}%`;
  return "→";
}

export function trendColor(trend?: XhsTrendInfo): string {
  if (!trend) return "default";
  if (trend.direction === "up") return "red";
  if (trend.direction === "down") return "green";
  return "default";
}
