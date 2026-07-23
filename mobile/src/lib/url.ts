type QueryValue = string | number | boolean | null | undefined;

export function normalizeBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(trimmed)) {
    throw new Error("Use a full http:// or https:// address.");
  }
  return trimmed;
}

export function apiUrl(
  baseUrl: string,
  path: string,
  query?: Record<string, QueryValue>
): string {
  const base = normalizeBaseUrl(baseUrl);
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });
  const suffix = params.toString();
  return `${base}${cleanPath}${suffix ? `?${suffix}` : ""}`;
}
