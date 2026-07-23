import { router } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { BrandHeader, ErrorState, LoadingState, Screen, StaleBanner } from "@/components/ui";
import { useRemote } from "@/hooks/useRemote";
import { colors, radius, spacing } from "@/theme";

export default function TeamsScreen() {
  const remote = useRemote<string[]>("/teams");
  return (
    <Screen refreshing={remote.refreshing} onRefresh={remote.reload}>
      <BrandHeader
        eyebrow="Team intelligence"
        title="Team rooms"
        description="Open any club for record, form, rotation, four factors, and recent results."
      />
      {remote.stale ? <StaleBanner /> : null}
      {remote.loading ? <LoadingState label="Loading the league…" /> : null}
      {remote.error ? <ErrorState message={remote.error} onRetry={remote.reload} /> : null}
      <View style={styles.grid}>
        {remote.data?.map((team) => (
          <Pressable
            key={team}
            accessibilityLabel={`Open ${team} team room`}
            accessibilityRole="button"
            onPress={() =>
              router.push({
                pathname: "/team/[code]",
                params: { code: team }
              })
            }
            style={({ pressed }) => [styles.team, pressed && styles.pressed]}
          >
            <View style={styles.mark}><Text style={styles.markText}>{team.slice(0, 1)}</Text></View>
            <Text style={styles.code}>{team}</Text>
            <Text style={styles.open}>OPEN ROOM →</Text>
          </Pressable>
        ))}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  team: {
    width: "48%",
    minHeight: 142,
    justifyContent: "space-between",
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.panel,
    borderWidth: 1,
    borderColor: colors.line
  },
  pressed: { opacity: 0.7, transform: [{ scale: 0.98 }] },
  mark: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.panel2,
    alignItems: "center",
    justifyContent: "center"
  },
  markText: { color: colors.orange, fontWeight: "900" },
  code: { color: colors.paper, fontSize: 27, fontWeight: "900" },
  open: { color: colors.muted2, fontSize: 9, fontWeight: "900", letterSpacing: 0.6 }
});
