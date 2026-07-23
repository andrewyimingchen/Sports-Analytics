export function number(value: unknown, digits = 1): string {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

export function integer(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed).toLocaleString() : "—";
}

export function percent(value: unknown, digits = 0): string {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(digits)}%` : "—";
}

export function statPercentile(value: unknown): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  const rank = Math.round(parsed);
  const mod100 = rank % 100;
  const suffix =
    mod100 >= 11 && mod100 <= 13
      ? "th"
      : rank % 10 === 1
        ? "st"
        : rank % 10 === 2
          ? "nd"
          : rank % 10 === 3
            ? "rd"
            : "th";
  return `${rank}${suffix}`;
}

export function money(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
    notation: "compact"
  }).format(parsed);
}

export function shortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
