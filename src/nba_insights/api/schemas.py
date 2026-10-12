"""Public response contracts for the POSSESSION LAB API.

Every model forbids undeclared fields, so a route that starts returning a new
key fails its tests instead of silently drifting from the documented schema.
Tabular payloads built from pandas frames stay as ``Records``: their columns
follow stats.nba.com names and vary with upstream availability, so the schema
documents them as row objects rather than pinning every column.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

Record = dict[str, Any]
Records = list[Record]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorResponse(Schema):
    detail: str | Records = Field(
        description=(
            "Human-readable reason the request failed; request validation errors "
            "carry FastAPI's list of field errors instead."
        )
    )


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries for the HTTPException codes a route raises."""
    descriptions = {
        401: "A valid API key is required for remote access",
        403: "Remote access to this endpoint is disabled",
        404: "The requested player, team, game, or record does not exist",
        422: "The request parameters are invalid for this route",
        429: "The request budget for this client is exhausted",
        502: "An upstream provider failed while answering",
        503: "A required model artifact or upstream dataset is unavailable",
    }
    return {code: {"model": ErrorResponse, "description": descriptions[code]} for code in codes}


# --- system -----------------------------------------------------------------


class ModelAvailability(Schema):
    outcome: bool
    points: bool
    lineup: bool


class Health(Schema):
    status: str


class Readiness(Schema):
    status: str
    pwa_shell: bool
    optional_models: ModelAvailability


class Capabilities(Schema):
    ask_ai: bool
    private_salary: str
    models: ModelAvailability


class Meta(Schema):
    current_season: str
    seasons: list[str]
    prediction_seasons: list[str]
    capabilities: Capabilities


# --- league -----------------------------------------------------------------


class SlateGame(Schema):
    home: str
    away: str
    tipoff: str
    home_win_prob: float


class LeaguePulse(Schema):
    season: str
    minimum_games: int
    leaders: dict[str, Records] = Field(description="Top five per stat label.")
    team_form: Records
    next_slate: list[SlateGame]


class SchemaAudit(Schema):
    available: list[str]
    missing: list[str]


class TrackingSource(Schema):
    status: str = Field(description="available, empty, or unavailable")
    endpoint: str
    provider: str
    fetched_at: str | None = None
    age_seconds: float | None = None
    stale: bool | None = None
    upstream_rows: int | None = None
    schema_audit: SchemaAudit | None = None
    detail: str | None = Field(default=None, description="Failure reason when unavailable.")


class Tracking(Schema):
    season: str
    category: str
    label: str
    scope: str
    definitions: dict[str, str]
    percentage_metrics: list[str]
    available_metrics: list[str] | None = None
    missing_metrics: list[str] | None = None
    games_column: str | None = None
    minimum_games: int
    source: TrackingSource
    count: int
    records: Records
    share_url: str | None = None


class LeagueExplore(Schema):
    season: str
    rate: str
    count: int
    players: Records


# --- teams ------------------------------------------------------------------


class WinLoss(Schema):
    wins: int
    losses: int


class TeamFinances(Schema):
    local_only: bool
    access: str
    seasons: list[str]
    payroll: float
    contracts: Records


class TeamProfile(Schema):
    team: str
    season: str
    record: WinLoss
    scouting_take: str
    form: Record
    roster: Records
    four_factors: Record
    factor_labels: dict[str, str]
    league_form: Records
    recent_games: Records
    standings: Records
    lineups: Records
    on_off: Records
    finances: TeamFinances | None = Field(
        description="Contract book; present only for local or API-key requests."
    )


class Driver(Schema):
    feature: str
    raw_difference: float | None
    standardized_value: float | None
    log_odds_contribution: float
    odds_multiplier: float
    label: str
    favors: str = Field(description="Team tricode the feature favors, or neutral.")


class TeamComparison(Schema):
    home: str
    away: str
    season: str
    basis_season: str
    projection_mode: str
    home_win_prob: float
    sample: Record
    metrics: Records
    teams: dict[str, Record]
    head_to_head: Record
    drivers: list[Driver]
    limitations: list[str]
    share_url: str
    export_filename: str


# --- predictions --------------------------------------------------------------


class GamePrediction(Schema):
    home: str
    away: str
    season: str
    basis_season: str
    projection_mode: str
    home_win_prob: float


class ScoreLine(Schema):
    home: int
    away: int


class SimulationSummary(Schema):
    home_win_prob: float
    median_margin: float
    margin_p10: float
    margin_p90: float
    median_total: float
    overtime_prob: float


class HistogramBin(Schema):
    mid: float
    count: int


class Simulation(Schema):
    home: str
    away: str
    season: str
    basis_season: str
    projection_mode: str
    n_sims: int
    median_score: ScoreLine
    summary: SimulationSummary
    outcome_model_home_win_prob: float
    margin_histogram: list[HistogramBin]
    total_histogram: list[HistogramBin]


class RosterInputs(Schema):
    metadata: Record
    teams: Records
    players: Records


class ScenarioStrength(Schema):
    before_net_adjustment: float
    after_net_adjustment: float
    causal_players: list[str]


class ScenarioOutcome(Schema):
    team: str
    before: dict[str, float]
    after: dict[str, float]
    change: dict[str, float]
    strength: ScenarioStrength


class RosterScenario(Schema):
    scenario_id: str
    version: str
    season: str
    basis_season: str
    n_sims: int
    baseline_immutable: bool
    paired_simulation_seed: int
    changes: Records
    salary_validation: Records
    outcomes: list[ScenarioOutcome]
    rosters: Records
    methodology: str
    salary_method: str


class PlayerSeasonProjections(Schema):
    season: str
    basis_season: str
    version: str
    assumptions: str
    intervals: str
    awards_method: str
    holdout: Record
    award_probability_totals: dict[str, float]
    count: int
    players: Records


class Favorite(Schema):
    team: str
    probability: float


class Favorites(Schema):
    championship: Favorite
    nba_cup: Favorite


class NbaCup(Schema):
    source_url: str
    rules_url: str
    source_date: str
    schedule_complete: bool
    groups: dict[str, Records]
    assumption: str


class SeasonForecast(Schema):
    season: str
    basis_season: str
    projection_mode: str
    roster_inputs: Record | None
    n_sims: int
    conferences: dict[str, Records]
    favorites: Favorites
    nba_cup: NbaCup
    methodology: str


class PlayerPointsProjection(Schema):
    player: str
    opponent: str
    home: bool
    projected_points: float
    interval_80: list[float] | None
    last_5: float
    last_10: float
    games_in_sample: int


class LineupPrediction(Schema):
    team: str
    players: list[str]
    estimated_net_rating: float
    minutes_together: float
    win_probability_vs_average: float
    source: str = Field(description="observed_blend or per_36_proxy")


# --- methodology --------------------------------------------------------------


class RegistryEntry(Schema):
    kind: str
    status: str
    version: str
    data_cutoff: Any
    metrics: Record
    awards_status: Any = None
    roster_overlay: dict[str, str] | None = None
    beats_baseline: bool | None = None


class Evaluation(Schema):
    protocol: str
    leakage: str
    decision_metrics: list[str]


class JourneyStage(Schema):
    stage: str
    accuracy: float


class Methodology(Schema):
    evaluation: Evaluation
    metrics: Record
    registry: dict[str, RegistryEntry]
    season_backtest: Record
    journey: list[JourneyStage]
    models: dict[str, str]
    rejected: list[str]


class ManifestVerification(Schema):
    status: str = Field(
        description=(
            "verified (every recorded artifact matches), drift (one is missing, "
            "changed, or unrecorded), empty, or manifest_missing"
        )
    )
    artifacts: dict[str, str] = Field(
        description="Per artifact: match, mismatch, missing, or not_recorded."
    )


class ManifestSummary(Schema):
    status: str = Field(description="available or missing")
    updated_at: str | None
    verification: str


class ManifestReport(Schema):
    status: str = Field(description="available or missing")
    path: str
    verification: ManifestVerification
    manifest: Record | None = Field(
        description=(
            "models/manifest.json: per producing run, the command, configuration, code "
            "revision, data cutoffs, feature schema, source snapshot fingerprints, "
            "artifact hashes, and metrics with baselines."
        )
    )


class Registry(Schema):
    models: dict[str, RegistryEntry]
    season_backtest: Record
    manifest: ManifestSummary


# --- players ----------------------------------------------------------------


class PlayerSummary(Schema):
    id: int
    full_name: str
    is_active: bool


class Percentiles(Schema):
    player: str
    season: str
    percentiles: dict[str, float]


class PlayerInsights(Schema):
    player: str
    season: str
    ratings: Record
    league_percentiles: dict[str, float]
    position_group: str | None
    position_percentiles: dict[str, float]
    scouting_take: str
    draft: str | None = Field(description='Draft line such as "#41 overall, 2014 (DEN)".')


class PlayerShots(Schema):
    player: str
    season: str
    season_type: str
    attempts: Records
    zones: Records
    hexes: Records
    breakdown: Records
    quality: Record


class PlayerSplits(Schema):
    player: str
    season: str
    splits: dict[str, Records]


class PlayerOnOff(Schema):
    player: str
    season: str
    on_off: Record


class PlayerContract(Schema):
    player: str
    local_only: bool
    access: str
    salaries: dict[str, float]
    history: Records
    guaranteed: float | None


class PlayerGames(Schema):
    player: str
    season: str
    games: Records


class SimilarPlayers(Schema):
    player: str
    season: str
    similar: Records


class PlayerComparison(Schema):
    season: str
    stats: dict[str, Record]
    career: dict[str, Record]
    career_seasons: dict[str, Records]
    percentiles: dict[str, dict[str, float]]
    shot_quality: dict[str, Record]
    poster_png: str | None


# --- games ------------------------------------------------------------------


class Schedule(Schema):
    season: str
    games: Records


class BoxScore(Schema):
    game_id: str
    source: str
    teams: dict[str, Records]


class StoryAvailability(Schema):
    timeline: bool
    shot_locations: bool
    lineups: bool
    play_by_play: bool


class GameStory(Schema):
    """Either an availability notice (``available: false`` + ``reason``) or the story."""

    game_id: str
    available: bool
    reason: str | None = None
    availability: StoryAvailability | None = None
    home: str | None = None
    away: str | None = None
    timeline: Records | None = None
    turning_points: Records | None = None
    biggest_runs: Record | None = None
    lead_changes: int | None = None
    clutch_points: Record | None = None
    shots: Records | None = None
    shot_summary: Records | None = None
    shot_locations_available: bool | None = None
    advanced: Any = None
    lineups: Any = None
    feed: Records | None = None
    win_probability_method: str | None = None


# --- AI -----------------------------------------------------------------------


class Answer(Schema):
    answer: str
    model: str
    season: str
