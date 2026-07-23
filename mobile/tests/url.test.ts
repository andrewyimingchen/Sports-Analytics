import { describe, expect, it } from "vitest";

import { apiUrl, normalizeBaseUrl } from "../src/lib/url";

describe("API URLs", () => {
  it("normalizes trailing slashes", () => {
    expect(normalizeBaseUrl(" https://example.com/// ")).toBe("https://example.com");
  });

  it("requires an HTTP scheme", () => {
    expect(() => normalizeBaseUrl("example.com")).toThrow(/http/);
  });

  it("encodes query values and omits empty values", () => {
    expect(
      apiUrl("https://example.com/", "/predict/game", {
        home: "NYK",
        away: "LAL",
        season: "2026-27",
        unused: null
      })
    ).toBe("https://example.com/predict/game?home=NYK&away=LAL&season=2026-27");
  });
});
