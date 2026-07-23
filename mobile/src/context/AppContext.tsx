import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { createContext, PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";
import { Platform } from "react-native";

import type { SavedItem } from "@/api/types";
import { savedKey, toggleSaved } from "@/lib/favorites";
import { normalizeBaseUrl } from "@/lib/url";

const SETTINGS_KEY = "possession-lab:settings";
const SAVED_KEY = "possession-lab:saved";
const API_KEY = "possession-lab.api-key";

const defaultUrl =
  process.env.EXPO_PUBLIC_API_URL ??
  (Platform.OS === "android" ? "http://10.0.2.2:8000" : "http://127.0.0.1:8000");

interface AppContextValue {
  hydrated: boolean;
  baseUrl: string;
  apiKey: string;
  saved: SavedItem[];
  setConnection: (baseUrl: string, apiKey: string) => Promise<void>;
  toggleFavorite: (item: SavedItem) => Promise<void>;
  isSaved: (item: SavedItem) => boolean;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: PropsWithChildren) {
  const [hydrated, setHydrated] = useState(false);
  const [baseUrl, setBaseUrl] = useState(defaultUrl);
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState<SavedItem[]>([]);

  useEffect(() => {
    Promise.all([
      AsyncStorage.getItem(SETTINGS_KEY),
      AsyncStorage.getItem(SAVED_KEY),
      SecureStore.getItemAsync(API_KEY)
    ])
      .then(([settings, favorites, secret]) => {
        if (settings) setBaseUrl(JSON.parse(settings).baseUrl ?? defaultUrl);
        if (favorites) setSaved(JSON.parse(favorites));
        if (secret) setApiKey(secret);
      })
      .finally(() => setHydrated(true));
  }, []);

  const value = useMemo<AppContextValue>(
    () => ({
      hydrated,
      baseUrl,
      apiKey,
      saved,
      setConnection: async (nextUrl, nextKey) => {
        const normalized = normalizeBaseUrl(nextUrl);
        await AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify({ baseUrl: normalized }));
        if (nextKey) await SecureStore.setItemAsync(API_KEY, nextKey);
        else await SecureStore.deleteItemAsync(API_KEY);
        setBaseUrl(normalized);
        setApiKey(nextKey);
      },
      toggleFavorite: async (item) => {
        const next = toggleSaved(saved, item);
        setSaved(next);
        await AsyncStorage.setItem(SAVED_KEY, JSON.stringify(next));
      },
      isSaved: (item) => saved.some((candidate) => savedKey(candidate) === savedKey(item))
    }),
    [apiKey, baseUrl, hydrated, saved]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}
