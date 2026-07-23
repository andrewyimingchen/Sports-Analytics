import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

import { AppProvider } from "@/context/AppContext";
import { colors } from "@/theme";

export default function RootLayout() {
  return (
    <AppProvider>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.night },
          headerTintColor: colors.paper,
          headerShadowVisible: false,
          headerTitleStyle: { fontWeight: "800" },
          contentStyle: { backgroundColor: colors.night },
          headerBackButtonDisplayMode: "minimal"
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="player/[id]" options={{ title: "Player profile" }} />
        <Stack.Screen name="team/[code]" options={{ title: "Team room" }} />
        <Stack.Screen name="settings" options={{ title: "Connection" }} />
      </Stack>
    </AppProvider>
  );
}
