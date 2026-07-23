import { router } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import type { Leader, LeaguePulse } from "@/api/types";
import { ListRow } from "@/components/rows";
import {
  BrandHeader,
  Card,
  ErrorState,
  IconButton,
  LoadingState,
  Screen,
  SectionTitle,
  StaleBanner,
  Stat
} from "@/components/ui";
import { number, percent, shortDate } from "@/lib/format";
import { useRemote } from "@/hooks/useRemote";
import { colors, spacing } from "@/theme";

const boards = [
  { key: "points", label: "Scoring", stat: "PTS" },
  { key: "assists", label: "Playmaking", stat: "AST" },
  { key: "rebounds", label: "Rebounding", stat: "REB" }
] as const;

function playerValue(player: Leader, key: string): string {
  return number(player[key], 1);
}

export default function PulseScreen() {
  const remote = useRemote<LeaguePulse>("/league/pulse");
  const pulse = remote.data;
  const form = pulse?.team_form.slice(0, 8) ?? [];

  return (
    <Screen refreshing={remote.refreshing} onRefresh={remote.reload}>
      <BrandHeader
        eyebrow={pulse ? `${pulse.season} · Live intelligence` : "Live intelligence"}
        title="League pulse"
        description="The league at a glance: leaders, form, power, and the next slate."
        action={
          <IconButton
            icon="settings-outline"
            label="Connection settings"
            onPress={() => router.push("/settings")}
          />
        }
      />
      {remote.stale ? <StaleBanner /> : null}
      {remote.loading && !pulse ? <LoadingState /> : null}
      {remote.error && !pulse ? <ErrorState message={remote.error} onRetry={remote.reload} /> : null}

      {pulse ? (
        <>
          <SectionTitle title="Stat leaders" aside={`MIN ${pulse.minimum_games} GP`} />
          <View style={styles.boardGrid}>
            {boards.map(({ key, label, stat }) => {
              const leader = pulse.leaders[key]?.[0];
              return (
                <Card key={key} style={styles.leaderCard}>
                  <Text style={styles.kicker}>{label.toUpperCase()}</Text>
                  <Text numberOfLines={2} style={styles.leaderName}>
                    {leader?.PLAYER_NAME ?? "Unavailable"}
                  </Text>
                  <View style={styles.leaderFoot}>
                    <Text style={styles.team}>{leader?.TEAM_ABBREVIATION ?? "—"}</Text>
                    <Text style={styles.bigValue}>
                      {leader ? playerValue(leader, stat) : "—"}
                    </Text>
                  </View>
                </Card>
              );
            })}
          </View>

          <SectionTitle title="Power index" aside="FORM · NET · ELO" />
          <Card>
            {form.map((team, index) => (
              <ListRow
                key={String(team.team)}
                index={index}
                title={String(team.team ?? "—")}
                subtitle={`${percent(team.form_win_pct)} form · ${number(team.elo, 0)} Elo`}
                value={`${Number(team.form_net ?? 0) >= 0 ? "+" : ""}${number(team.form_net)}`}
                onPress={() =>
                  router.push({
                    pathname: "/team/[code]",
                    params: { code: String(team.team) }
                  })
                }
              />
            ))}
          </Card>

          <SectionTitle title="Next slate" aside="MODEL PROBABILITY" />
          {pulse.next_slate.length ? (
            <View style={styles.slates}>
              {pulse.next_slate.map((game) => (
                <Card key={`${game.away}-${game.home}`} style={styles.slate}>
                  <Text style={styles.kicker}>{shortDate(game.tipoff).toUpperCase()}</Text>
                  <Text style={styles.matchup}>{game.away} @ {game.home}</Text>
                  <View style={styles.stats}>
                    <Stat label={`${game.home} win`} value={percent(game.home_win_prob)} accent />
                    <Stat label={`${game.away} win`} value={percent(1 - game.home_win_prob)} />
                  </View>
                </Card>
              ))}
            </View>
          ) : (
            <Card>
              <Text style={styles.muted}>No upcoming games are available right now.</Text>
            </Card>
          )}
        </>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  boardGrid: { gap: spacing.sm },
  leaderCard: { minHeight: 142, justifyContent: "space-between" },
  kicker: { color: colors.orangeSoft, fontSize: 9, fontWeight: "900", letterSpacing: 1.2 },
  leaderName: { color: colors.paper, fontSize: 24, lineHeight: 26, fontWeight: "900", marginTop: 12 },
  leaderFoot: { flexDirection: "row", alignItems: "flex-end", justifyContent: "space-between" },
  team: { color: colors.muted, fontSize: 11, fontWeight: "800" },
  bigValue: { color: colors.lime, fontSize: 34, fontWeight: "900" },
  slates: { gap: spacing.sm },
  slate: { gap: spacing.sm },
  matchup: { color: colors.paper, fontSize: 23, fontWeight: "900" },
  stats: { flexDirection: "row", gap: spacing.lg },
  muted: { color: colors.muted, lineHeight: 20 }
});
