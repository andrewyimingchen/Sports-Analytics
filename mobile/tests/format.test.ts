import { describe, expect, it } from "vitest";

import { number, percent, statPercentile } from "../src/lib/format";

describe("display formatting", () => {
  it("formats basketball numbers", () => {
    expect(number(28.456)).toBe("28.5");
    expect(number(null)).toBe("—");
  });

  it("formats probabilities and percentile ranks", () => {
    expect(percent(0.683)).toBe("68%");
    expect(statPercentile(91.7)).toBe("92nd");
  });
});
