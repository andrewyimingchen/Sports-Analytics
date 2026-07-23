import { describe, expect, it } from "vitest";

import type { SavedItem } from "../src/api/types";
import { savedKey, toggleSaved } from "../src/lib/favorites";

const player: SavedItem = { type: "player", id: 2544, label: "LeBron James" };

describe("saved items", () => {
  it("uses type-specific stable keys", () => {
    expect(savedKey(player)).toBe("player:2544");
    expect(savedKey({ type: "team", id: "LAL", label: "LAL" })).toBe("team:LAL");
  });

  it("toggles an item without duplicating it", () => {
    const added = toggleSaved([], player);
    expect(added).toEqual([player]);
    expect(toggleSaved(added, player)).toEqual([]);
  });
});
