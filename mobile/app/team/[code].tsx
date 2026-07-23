import * as Haptics from "expo-haptics";
import { useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import type { JsonRecord, TeamProfile } from "@/api/types";
import { DataRow, ListRow } from "@/components/rows";
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
import { useApp } from "@/context/AppContext";
import { money, number, percent } from "@/lib/format";
import { useRemote } from "@/hooks/useRemote";
import { colors, spacing } from "@/theme";

function playerName(player: JsonRecord): string {
  return String(player.PLAYER_NAME ?? "Unknown player");
}

export default function TeamDetailScreen() {
  const params = useLocalSearchParams<{ code: string }>();
  const code = String(params.code).toUpperCase();
  const remote = useRemote<TeamProfile>(`/teams/${code}/profile`);
  const { isSaved, toggleFavorite } = useApp();
  const item = { type: "team" as const, id: code, label: code, subtitle: remote.data?.season };
  const saved = isSaved(item);
  const profile = remote.data;

  async function favorite() {
    await toggleFavorite(item);
    await Haptics.selectionAsync();
  }

  return (
    <Screen refreshing={remote.refreshing} onRefresh={remote.reload}>
      <BrandHeader
        eyebrow={profile ? `${profile.season} · Team room` : "Team room"}
        title={code}
        description={profile?.scouting_take}
        action={
          <IconButton
            icon={saved ? "bookmark" : "bookmark-outline"}
            label={saved ? "Remove team from saved" : "Save team"}
            active={saved}
            onPress={favorite}
          />
        }
      />
      {remote.stale ? <StaleBanner /> : null}
      {remote.loading && !profile ? <LoadingState label="Opening team room…" /> : null}
      {remote.error && !profile ? <ErrorState message={remote.error} onRetry={remote.reload} /> : null}
      {profile ? (
        <>
          <View style={styles.statRow}>
            <Card style={styles.statCard}>
              <Stat label="Record" value={`${profile.record.wins}–${profile.record.losses}`} accent />
            </Card>
            <Card style={styles.statCard}>
              <Stat label="Form win" value={percent(profile.form.form_win_pct)} />
            </Card>
            <Card style={styles.statCard}>
              <Stat
                label="Net form"
                value={`${Number(profile.form.form_net ?? 0) >= 0 ? "+" : ""}${number(profile.form.form_net)}`}
              />
            </Card>
          </View>

          <SectionTitle title="Four factors" aside="TEAM PROFILE" />
          <Card>
            {Object.entries(profile.four_factors)
              .filter(([, value]) => typeof value === "number")
              .slice(0, 8)
              .map(([label, value], index, all) => (
                <DataRow
                  key={label}
                  label={label.replaceAll("_", " ")}
                  value={number(value, 2)}
                  last={index === all.length - 1}
                />
              ))}
          </Card>

          <SectionTitle title="Rotation" aside={`${profile.roster.length} PLAYERS`} />
          <Card>
            {profile.roster.map((player) => (
              <ListRow
                key={String(player.PLAYER_ID ?? playerName(player))}
                title={playerName(player)}
                subtitle={`${number(player.MIN)} MIN · ${number(player.REB)} REB · ${number(player.AST)} AST`}
                value={`${number(player.PTS)} PTS`}
              />
            ))}
          </Card>

          <SectionTitle title="Last games" aside="RECENT FORM" />
          <Card>
            {profile.recent_games.map((game, index) => (
              <ListRow
                key={`${game.GAME_DATE}-${index}`}
                title={String(game.MATCHUP ?? "Game")}
                subtitle={String(game.GAME_DATE ?? "")}
                value={`${game.WL ?? "—"} ${number(game.PLUS_MINUS, 0)}`}
              />
            ))}
          </Card>

          {profile.finances ? (
            <>
              <SectionTitle title="Payroll" aside="AUTHORIZED DATA" />
              <Card>
                <Text style={styles.payroll}>{money(profile.finances.payroll)}</Text>
                <Text style={styles.caption}>Current committed payroll from the private salary feed.</Text>
              </Card>
            </>
          ) : null}
        </>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  statRow: { flexDirection: "row", gap: spacing.sm },
  statCard: { flex: 1, paddingHorizontal: spacing.sm },
  payroll: { color: colors.lime, fontSize: 36, fontWeight: "900" },
  caption: { color: colors.muted, fontSize: 11, marginTop: spacing.xs }
});
