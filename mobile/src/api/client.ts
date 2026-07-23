import AsyncStorage from "@react-native-async-storage/async-storage";

import { apiUrl } from "@/lib/url";

const CACHE_PREFIX = "possession-lab:response:";
const TIMEOUT_MS = 18_000;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  query?: Record<string, string | number | boolean | null | undefined>;
  apiKey?: string;
  signal?: AbortSignal;
  cache?: boolean;
}

export interface ApiResult<T> {
  data: T;
  stale: boolean;
}

function messageFromPayload(payload: unknown, fallback: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return fallback;
}

export async function getJson<T>(
  baseUrl: string,
  path: string,
  options: RequestOptions = {}
): Promise<ApiResult<T>> {
  const url = apiUrl(baseUrl, path, options.query);
  const cacheKey = `${CACHE_PREFIX}${url}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort);
  try {
    const response = await fetch(url, {
      headers: options.apiKey ? { "X-API-Key": options.apiKey } : undefined,
      signal: controller.signal
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(
        messageFromPayload(payload, `Request failed (${response.status})`),
        response.status
      );
    }
    if (options.cache !== false) {
      await AsyncStorage.setItem(
        cacheKey,
        JSON.stringify({ savedAt: Date.now(), payload })
      ).catch(() => undefined);
    }
    return { data: payload as T, stale: false };
  } catch (error) {
    if (options.cache !== false) {
      const cached = await AsyncStorage.getItem(cacheKey).catch(() => null);
      if (cached) {
        const parsed = JSON.parse(cached) as { payload: T };
        return { data: parsed.payload, stale: true };
      }
    }
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiError("The server took too long to respond.");
    }
    throw new ApiError("Could not reach POSSESSION LAB. Check the server address.");
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abort);
  }
}
