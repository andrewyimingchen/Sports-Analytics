import type { SavedItem } from "../api/types";

export function savedKey(item: SavedItem): string {
  return `${item.type}:${item.id}`;
}

export function toggleSaved(items: SavedItem[], target: SavedItem): SavedItem[] {
  const key = savedKey(target);
  if (items.some((item) => savedKey(item) === key)) {
    return items.filter((item) => savedKey(item) !== key);
  }
  return [target, ...items];
}
