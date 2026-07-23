export type JsonRecord = Record<string, string | number | boolean | null | undefined>;

export interface Meta {
  current_season: string;
  seasons: string[];
  prediction_seasons: string[];
}

export interface PlayerSearchResult {
  id: number;
  full_name: string;
  is_active: boolean;
}

export interface Leader extends JsonRecord {
  PLAYER_ID?: number;
  PLAYER_NAME?: string;
  TEAM_ABBREVIATION?: string;
  PTS?: number;
  AST?: number;
  REB?: number;
  FG3M?: number;
  NET_RATING?: number;
  CLUTCH_NET_RATING?: number;
}

export interface TeamForm extends JsonRecord {
  team?: string;
  form_win_pct?: number;
  form_pts?: number;
  form_net?: number;
  elo?: number;
}

export interface SlateGame {
  home: string;
  away: string;
  tipoff: string;
  home_win_prob: number;
}

export interface LeaguePulse {
  season: string;
  minimum_games: number;
  leaders: Record<string, Leader[]>;
  team_form: TeamForm[];
  next_slate: SlateGame[];
}

export interface PlayerInsights {
  player: string;
  season: string;
  ratings: JsonRecord;
  league_percentiles: Record<string, number>;
  position_group: string | null;
  position_percentiles: Record<string, number>;
  scouting_take: string;
  draft: string | JsonRecord | null;
}

export interface PlayerGames {
  player: string;
  season: string;
  games: JsonRecord[];
}

export interface TeamProfile {
  team: string;
  season: string;
  record: { wins: number; losses: number };
  scouting_take: string;
  form: JsonRecord;
  roster: JsonRecord[];
  four_factors: JsonRecord;
  recent_games: JsonRecord[];
  standings: JsonRecord[];
  lineups: JsonRecord[];
  on_off: JsonRecord[];
  finances: null | {
    payroll: number;
    contracts: JsonRecord[];
  };
}

export interface GamePrediction {
  home: string;
  away: string;
  season: string;
  basis_season: string;
  projection_mode: string;
  home_win_prob: number;
}

export type SavedItem =
  | { type: "player"; id: number; label: string; subtitle?: string }
  | { type: "team"; id: string; label: string; subtitle?: string };
