import Ionicons from "@expo/vector-icons/Ionicons";
import { Tabs } from "expo-router";

import { colors } from "@/theme";

const icons: Record<string, keyof typeof Ionicons.glyphMap> = {
  index: "pulse",
  players: "person",
  teams: "shield",
  matchup: "analytics",
  saved: "bookmark"
};

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: colors.orange,
        tabBarInactiveTintColor: colors.muted2,
        tabBarStyle: {
          position: "absolute",
          backgroundColor: colors.night2,
          borderTopColor: colors.line,
          height: 82,
          paddingTop: 8,
          paddingBottom: 12
        },
        tabBarLabelStyle: { fontSize: 10, fontWeight: "800" },
        tabBarIcon: ({ color, size }) => (
          <Ionicons name={icons[route.name] ?? "ellipse"} color={color} size={size} />
        )
      })}
    >
      <Tabs.Screen name="index" options={{ title: "Pulse" }} />
      <Tabs.Screen name="players" options={{ title: "Players" }} />
      <Tabs.Screen name="teams" options={{ title: "Teams" }} />
      <Tabs.Screen name="matchup" options={{ title: "Matchup" }} />
      <Tabs.Screen name="saved" options={{ title: "Saved" }} />
    </Tabs>
  );
}
