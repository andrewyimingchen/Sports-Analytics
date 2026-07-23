import * as Haptics from "expo-haptics";
import { useMemo, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { getJson } from "@/api/client";
import type { GamePrediction, Meta } from "@/api/types";
import {
  BrandHeader,
  Card,
  ErrorState,
  LoadingState,
  Pill,
  PrimaryButton,
  Screen,
  SectionTitle,
  Stat
} from "@/components/ui";
import { useApp } from "@/context/AppContext";
import { percent } from "@/lib/format";
import { useRemote } from "@/hooks/useRemote";
import { colors, radius, spacing } from "@/theme";

function TeamPicker({
  label,
  teams,
  value,
  onChange
}: {
  label: string;
  teams: string[];
  value: string;
  onChange: (team: string) => void;
}) {
  return (
    <View style={styles.picker}>
      <Text style={styles.pickerLabel}>{label.toUpperCase()}</Text>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.pills}
      >
        {teams.map((team) => (
          <Pill key={team} label={team} selected={team === value} onPress={() => onChange(team)} />
        ))}
      </ScrollView>
    </View>
  );
}

export default function MatchupScreen() {
  const { baseUrl, apiKey } = useApp();
  const teams = useRemote<string[]>("/teams");
  const meta = useRemote<Meta>("/meta");
  const [homeChoice, setHomeChoice] = useState("");
  const [awayChoice, setAwayChoice] = useState("");
  const [seasonChoice, setSeasonChoice] = useState("");
  const [prediction, setPrediction] = useState<GamePrediction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const home = homeChoice || teams.data?.[1] || "";
  const away = awayChoice || teams.data?.[0] || "";
  const season = seasonChoice || meta.data?.prediction_seasons[0] || "";

  const canRun = Boolean(home && away && home !== away && season && !loading);
  const awayProbability = useMemo(
    () => prediction ? 1 - prediction.home_win_prob : 0,
    [prediction]
  );

  async function runPrediction() {
    if (!canRun) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getJson<GamePrediction>(baseUrl, "/predict/game", {
        apiKey,
        query: { home, away, season },
        cache: false
      });
      setPrediction(result.data);
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (caught) {
      setPrediction(null);
      setError(caught instanceof Error ? caught.message : "Prediction unavailable.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Screen>
      <BrandHeader
        eyebrow="Calibrated outcome model"
        title="Matchup lab"
        description="Choose a road team, home team, and forecast season. The backend model handles the math."
      />
      {teams.loading || meta.loading ? <LoadingState label="Preparing matchup inputs…" /> : null}
      {teams.error ? <ErrorState message={teams.error} onRetry={teams.reload} /> : null}
      {teams.data ? (
        <>
          <TeamPicker label="Away" teams={teams.data} value={away} onChange={setAwayChoice} />
          <TeamPicker label="Home" teams={teams.data} value={home} onChange={setHomeChoice} />
          {meta.data ? (
            <View style={styles.picker}>
              <Text style={styles.pickerLabel}>FORECAST SEASON</Text>
              <View style={styles.pills}>
                {meta.data.prediction_seasons.map((item) => (
                  <Pill
                    key={item}
                    label={item}
                    selected={season === item}
                    onPress={() => setSeasonChoice(item)}
                  />
                ))}
              </View>
            </View>
          ) : null}
          {home === away && home ? (
            <Text style={styles.validation}>Home and away teams must be different.</Text>
          ) : null}
          <PrimaryButton
            label={loading ? "Running model…" : "Run prediction"}
            icon="sparkles"
            disabled={!canRun}
            onPress={runPrediction}
          />
        </>
      ) : null}
      {error ? <ErrorState message={error} onRetry={runPrediction} /> : null}
      {prediction ? (
        <>
          <SectionTitle title="Model result" aside={prediction.season} />
          <Card style={styles.result}>
            <Text style={styles.resultEyebrow}>{prediction.away} AT {prediction.home}</Text>
            <View style={styles.probabilityRing}>
              <Text style={styles.probability}>{percent(prediction.home_win_prob)}</Text>
              <Text style={styles.probabilityLabel}>{prediction.home} WIN</Text>
            </View>
            <View style={styles.statRow}>
              <Stat label={`${prediction.home} win`} value={percent(prediction.home_win_prob)} accent />
              <Stat label={`${prediction.away} win`} value={percent(awayProbability)} />
            </View>
            <Text style={styles.basis}>
              {prediction.projection_mode.replaceAll("_", " ")} · data basis {prediction.basis_season}
            </Text>
          </Card>
          <Card>
            <Text style={styles.noteTitle}>READ THIS NUMBER CORRECTLY</Text>
            <Text style={styles.note}>
              This is a probability, not a promise. It uses team form, efficiency, schedule context,
              carried-over Elo, and home court from the server’s evaluated model.
            </Text>
          </Card>
        </>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  picker: { gap: spacing.sm },
  pickerLabel: { color: colors.muted, fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  validation: { color: colors.red, fontSize: 12 },
  result: { alignItems: "center", gap: spacing.lg, paddingVertical: spacing.xl },
  resultEyebrow: { color: colors.orangeSoft, fontSize: 11, fontWeight: "900", letterSpacing: 1.4 },
  probabilityRing: {
    width: 164,
    height: 164,
    borderRadius: 82,
    borderWidth: 13,
    borderColor: colors.orange,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.night2
  },
  probability: { color: colors.paper, fontSize: 42, fontWeight: "900", letterSpacing: -1.5 },
  probabilityLabel: { color: colors.muted, fontSize: 9, fontWeight: "900" },
  statRow: { flexDirection: "row", gap: spacing.xl, width: "100%" },
  basis: {
    color: colors.muted2,
    backgroundColor: colors.panel2,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    overflow: "hidden",
    fontSize: 10,
    textTransform: "uppercase"
  },
  noteTitle: { color: colors.lime, fontSize: 10, fontWeight: "900", marginBottom: spacing.sm },
  note: { color: colors.muted, fontSize: 12, lineHeight: 19 }
});
