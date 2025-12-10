"""
NBA Statistics Downloader using nba_api
This script uses the official nba_api library to fetch NBA statistics from stats.nba.com
Alternative to Basketball Reference which is blocking scraping
"""

from nba_api.stats.endpoints import (
    playergamelog, leaguegamefinder, leaguedashplayerstats,
    teamgamelog, commonteamroster, leaguestandings,
    playercareerstats, playerprofilev2, teamdashboardbygeneralsplits,
    boxscoretraditionalv2, shotchartdetail, playerawards,
    playerdashboardbyyearoveryear, teamyearbyyearstats
)
from nba_api.stats.static import players, teams
import pandas as pd
import os
import json
from datetime import datetime
import logging
import time

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('nba_api_downloader.log'),
        logging.StreamHandler()
    ]
)

class NBAAPIDownloader:
    def __init__(self, delay=0.6):
        """
        Initialize the NBA API downloader

        Args:
            delay (float): Delay between API calls in seconds (default: 0.6)
                          NBA API rate limits requests, so add delay to be safe
        """
        self.data_dir = "nba_api_data"
        self._create_directories()
        self.delay = delay
        self.current_season = "2024-25"  # Update this as needed

    def _create_directories(self):
        """Create directories for storing downloaded data"""
        directories = [
            self.data_dir,
            f"{self.data_dir}/players",
            f"{self.data_dir}/teams",
            f"{self.data_dir}/seasons",
            f"{self.data_dir}/games",
            f"{self.data_dir}/box_scores",
            f"{self.data_dir}/shot_charts"
        ]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)

    def _rate_limit(self):
        """Add delay to respect NBA API rate limits"""
        time.sleep(self.delay)

    def get_all_players(self):
        """
        Get a list of all NBA players

        Returns:
            list: List of player dictionaries with id, full_name, first_name, last_name
        """
        try:
            logging.info("Fetching all players")
            all_players = players.get_players()
            logging.info(f"Retrieved {len(all_players)} players")
            return all_players
        except Exception as e:
            logging.error(f"Error fetching players: {e}")
            return []

    def get_all_teams(self):
        """
        Get a list of all NBA teams

        Returns:
            list: List of team dictionaries with id, full_name, abbreviation, nickname, city, state, year_founded
        """
        try:
            logging.info("Fetching all teams")
            all_teams = teams.get_teams()
            logging.info(f"Retrieved {len(all_teams)} teams")
            return all_teams
        except Exception as e:
            logging.error(f"Error fetching teams: {e}")
            return []

    def find_player(self, name):
        """
        Find a player by name

        Args:
            name (str): Player name (full or partial)

        Returns:
            list: List of matching player dictionaries
        """
        try:
            logging.info(f"Searching for player: {name}")
            all_players = players.find_players_by_full_name(name)
            logging.info(f"Found {len(all_players)} matches")
            return all_players
        except Exception as e:
            logging.error(f"Error searching for player: {e}")
            return []

    def get_player_career_stats(self, player_id):
        """
        Get complete career statistics for a player

        Args:
            player_id (int): NBA player ID

        Returns:
            dict: Dictionary containing career stats DataFrames
        """
        try:
            logging.info(f"Fetching career stats for player ID: {player_id}")
            self._rate_limit()
            career = playercareerstats.PlayerCareerStats(player_id=player_id)

            # Get all available data
            data = {
                'season_totals_regular_season': career.season_totals_regular_season.get_data_frame(),
                'career_totals_regular_season': career.career_totals_regular_season.get_data_frame(),
                'season_totals_post_season': career.season_totals_post_season.get_data_frame(),
                'career_totals_post_season': career.career_totals_post_season.get_data_frame()
            }

            logging.info(f"Retrieved career stats")
            return data
        except Exception as e:
            logging.error(f"Error fetching player career stats: {e}")
            return {}

    def get_player_game_log(self, player_id, season="2024-25", season_type="Regular Season"):
        """
        Get game log for a specific player and season

        Args:
            player_id (int): NBA player ID
            season (str): Season in format "YYYY-YY" (e.g., "2024-25")
            season_type (str): "Regular Season" or "Playoffs"

        Returns:
            DataFrame: Game log data
        """
        try:
            logging.info(f"Fetching game log for player ID: {player_id}, season: {season}")
            self._rate_limit()
            game_log = playergamelog.PlayerGameLog(
                player_id=player_id,
                season=season,
                season_type_all_star=season_type
            )
            df = game_log.get_data_frames()[0]
            logging.info(f"Retrieved {len(df)} games")
            return df
        except Exception as e:
            logging.error(f"Error fetching player game log: {e}")
            return pd.DataFrame()

    def get_league_leaders(self, season="2024-25", stat_category="PTS", per_mode="PerGame"):
        """
        Get league leaders for a specific stat

        Args:
            season (str): Season in format "YYYY-YY"
            stat_category (str): Stat to rank by (PTS, REB, AST, STL, BLK, FG_PCT, etc.)
            per_mode (str): "PerGame", "Totals", or "Per36"

        Returns:
            DataFrame: League leaders data
        """
        try:
            logging.info(f"Fetching league leaders for {stat_category} in {season}")
            self._rate_limit()
            stats = leaguedashplayerstats.LeagueDashPlayerStats(
                season=season,
                per_mode_detailed=per_mode,
                measure_type_detailed_defense="Base"
            )
            df = stats.get_data_frames()[0]

            # Sort by the requested stat
            if stat_category in df.columns:
                df = df.sort_values(by=stat_category, ascending=False)

            logging.info(f"Retrieved stats for {len(df)} players")
            return df
        except Exception as e:
            logging.error(f"Error fetching league leaders: {e}")
            return pd.DataFrame()

    def get_team_game_log(self, team_id, season="2024-25", season_type="Regular Season"):
        """
        Get game log for a specific team and season

        Args:
            team_id (int): NBA team ID
            season (str): Season in format "YYYY-YY"
            season_type (str): "Regular Season" or "Playoffs"

        Returns:
            DataFrame: Team game log data
        """
        try:
            logging.info(f"Fetching team game log for team ID: {team_id}, season: {season}")
            self._rate_limit()
            game_log = teamgamelog.TeamGameLog(
                team_id=team_id,
                season=season,
                season_type_all_star=season_type
            )
            df = game_log.get_data_frames()[0]
            logging.info(f"Retrieved {len(df)} games")
            return df
        except Exception as e:
            logging.error(f"Error fetching team game log: {e}")
            return pd.DataFrame()

    def get_team_roster(self, team_id, season="2024-25"):
        """
        Get current roster for a team

        Args:
            team_id (int): NBA team ID
            season (str): Season in format "YYYY-YY"

        Returns:
            DataFrame: Team roster data
        """
        try:
            logging.info(f"Fetching roster for team ID: {team_id}, season: {season}")
            self._rate_limit()
            roster = commonteamroster.CommonTeamRoster(
                team_id=team_id,
                season=season
            )
            df = roster.get_data_frames()[0]
            logging.info(f"Retrieved {len(df)} players")
            return df
        except Exception as e:
            logging.error(f"Error fetching team roster: {e}")
            return pd.DataFrame()

    def get_league_standings(self, season="2024-25"):
        """
        Get current league standings

        Args:
            season (str): Season in format "YYYY-YY"

        Returns:
            DataFrame: League standings data
        """
        try:
            logging.info(f"Fetching league standings for {season}")
            self._rate_limit()
            standings = leaguestandings.LeagueStandings(
                season=season,
                season_type="Regular Season"
            )
            df = standings.get_data_frames()[0]
            logging.info(f"Retrieved standings for {len(df)} teams")
            return df
        except Exception as e:
            logging.error(f"Error fetching league standings: {e}")
            return pd.DataFrame()

    def get_box_score(self, game_id):
        """
        Get detailed box score for a specific game

        Args:
            game_id (str): NBA game ID (e.g., "0022400001")

        Returns:
            dict: Dictionary containing player and team stats DataFrames
        """
        try:
            logging.info(f"Fetching box score for game ID: {game_id}")
            self._rate_limit()
            boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)

            data = {
                'player_stats': boxscore.player_stats.get_data_frame(),
                'team_stats': boxscore.team_stats.get_data_frame(),
                'team_starter_bench_stats': boxscore.team_starter_bench_stats.get_data_frame()
            }

            logging.info(f"Retrieved box score")
            return data
        except Exception as e:
            logging.error(f"Error fetching box score: {e}")
            return {}

    def get_shot_chart(self, player_id, season="2024-25", season_type="Regular Season"):
        """
        Get shot chart data for a player

        Args:
            player_id (int): NBA player ID
            season (str): Season in format "YYYY-YY"
            season_type (str): "Regular Season" or "Playoffs"

        Returns:
            DataFrame: Shot chart data with location and result for each shot
        """
        try:
            logging.info(f"Fetching shot chart for player ID: {player_id}, season: {season}")
            self._rate_limit()
            shot_chart = shotchartdetail.ShotChartDetail(
                team_id=0,
                player_id=player_id,
                season_nullable=season,
                season_type_all_star=season_type,
                context_measure_simple="FGA"
            )
            df = shot_chart.get_data_frames()[0]
            logging.info(f"Retrieved {len(df)} shots")
            return df
        except Exception as e:
            logging.error(f"Error fetching shot chart: {e}")
            return pd.DataFrame()

    def get_team_stats(self, team_id, season="2024-25"):
        """
        Get comprehensive team statistics

        Args:
            team_id (int): NBA team ID
            season (str): Season in format "YYYY-YY"

        Returns:
            dict: Dictionary containing various team stats DataFrames
        """
        try:
            logging.info(f"Fetching team stats for team ID: {team_id}, season: {season}")
            self._rate_limit()
            team_dashboard = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                team_id=team_id,
                season=season
            )

            data = {
                'overall': team_dashboard.overall_team_dashboard.get_data_frame(),
                'location': team_dashboard.location_team_dashboard.get_data_frame(),
                'win_loss': team_dashboard.win_losses_team_dashboard.get_data_frame(),
                'month': team_dashboard.month_team_dashboard.get_data_frame()
            }

            logging.info(f"Retrieved team stats")
            return data
        except Exception as e:
            logging.error(f"Error fetching team stats: {e}")
            return {}

    def find_games_by_date(self, date_from="01/01/2024", date_to="01/31/2024"):
        """
        Find all games within a date range

        Args:
            date_from (str): Start date in format "MM/DD/YYYY"
            date_to (str): End date in format "MM/DD/YYYY"

        Returns:
            DataFrame: Games data
        """
        try:
            logging.info(f"Fetching games from {date_from} to {date_to}")
            self._rate_limit()
            gamefinder = leaguegamefinder.LeagueGameFinder(
                date_from_nullable=date_from,
                date_to_nullable=date_to
            )
            df = gamefinder.get_data_frames()[0]
            logging.info(f"Retrieved {len(df)} game records")
            return df
        except Exception as e:
            logging.error(f"Error fetching games: {e}")
            return pd.DataFrame()

    def save_data(self, data, filename, data_type='csv'):
        """
        Save downloaded data to file

        Args:
            data: Data to save (DataFrame, dict, or list)
            filename (str): Name of the file (without extension)
            data_type (str): Type of file ('csv' or 'json')
        """
        try:
            if data_type == 'json':
                filepath = f"{self.data_dir}/{filename}.json"
                if isinstance(data, pd.DataFrame):
                    data.to_json(filepath, orient='records', indent=2)
                else:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                logging.info(f"Data saved to {filepath}")
            elif data_type == 'csv':
                filepath = f"{self.data_dir}/{filename}.csv"
                if isinstance(data, pd.DataFrame):
                    data.to_csv(filepath, index=False)
                elif isinstance(data, dict):
                    # Save each DataFrame in dict separately
                    for key, df in data.items():
                        if isinstance(df, pd.DataFrame):
                            df_path = f"{self.data_dir}/{filename}_{key}.csv"
                            df.to_csv(df_path, index=False)
                            logging.info(f"Data saved to {df_path}")
                else:
                    pd.DataFrame(data).to_csv(filepath, index=False)
                    logging.info(f"Data saved to {filepath}")
        except Exception as e:
            logging.error(f"Error saving data: {e}")


def main():
    """
    Main function to demonstrate usage of the NBA API downloader
    """
    # Initialize downloader
    downloader = NBAAPIDownloader(delay=0.6)

    print("NBA Statistics Downloader using nba_api")
    print("=" * 60)
    print("Data source: stats.nba.com via nba_api")
    print("=" * 60)

    # Example 1: Get all players and teams
    print("\nExample 1: Getting all players and teams")
    all_players = downloader.get_all_players()
    all_teams = downloader.get_all_teams()
    print(f"Total players: {len(all_players)}")
    print(f"Total teams: {len(all_teams)}")

    # Save the lists
    downloader.save_data(all_players, "players/all_players", 'json')
    downloader.save_data(all_teams, "teams/all_teams", 'json')

    # Example 2: Find a specific player
    print("\nExample 2: Searching for LeBron James")
    lebron = downloader.find_player("LeBron James")
    if lebron:
        print(f"Found: {lebron[0]['full_name']} (ID: {lebron[0]['id']})")
        lebron_id = lebron[0]['id']

        # Get LeBron's career stats
        print("  Fetching career stats...")
        career_stats = downloader.get_player_career_stats(lebron_id)
        if career_stats:
            downloader.save_data(career_stats, "players/lebron_james_career", 'csv')
            print(f"  Career stats saved")

        # Get LeBron's current season game log
        print("  Fetching 2024-25 game log...")
        game_log = downloader.get_player_game_log(lebron_id, season="2024-25")
        if not game_log.empty:
            downloader.save_data(game_log, "players/lebron_james_2024_25_gamelog", 'csv')
            print(f"  Game log saved ({len(game_log)} games)")

    # Example 3: Get league leaders
    print("\nExample 3: Top scorers for 2024-25 season")
    scoring_leaders = downloader.get_league_leaders(
        season="2024-25",
        stat_category="PTS",
        per_mode="PerGame"
    )
    if not scoring_leaders.empty:
        print("Top 5 scorers:")
        for idx, player in scoring_leaders.head(5).iterrows():
            print(f"  {idx+1}. {player['PLAYER_NAME']} - {player['PTS']:.1f} PPG")
        downloader.save_data(scoring_leaders, "seasons/2024_25_scoring_leaders", 'csv')

    # Example 4: Get league standings
    print("\nExample 4: Current league standings")
    standings = downloader.get_league_standings(season="2024-25")
    if not standings.empty:
        print(f"Retrieved standings for {len(standings)} teams")
        print("Top 5 teams:")
        standings_sorted = standings.sort_values('WinPCT', ascending=False)
        for idx, team in standings_sorted.head(5).iterrows():
            print(f"  {idx+1}. {team['TeamName']} - {team['Record']} ({team['WinPCT']:.3f})")
        downloader.save_data(standings, "seasons/2024_25_standings", 'csv')

    # Example 5: Get team roster
    print("\nExample 5: Lakers roster")
    lakers = [t for t in all_teams if t['full_name'] == 'Los Angeles Lakers']
    if lakers:
        lakers_id = lakers[0]['id']
        roster = downloader.get_team_roster(lakers_id, season="2024-25")
        if not roster.empty:
            print(f"Lakers have {len(roster)} players")
            downloader.save_data(roster, "teams/lakers_roster_2024_25", 'csv')

    # Example 6: Get games from a date range
    print("\nExample 6: Games from November 2024")
    games = downloader.find_games_by_date(
        date_from="11/01/2024",
        date_to="11/30/2024"
    )
    if not games.empty:
        print(f"Found {len(games)} game records in November 2024")
        downloader.save_data(games, "games/november_2024", 'csv')

    print(f"\nAll data saved in '{downloader.data_dir}' directory")
    print("\n" + "=" * 60)
    print("Additional capabilities:")
    print("  - get_player_career_stats() - Complete career statistics")
    print("  - get_shot_chart() - Shot location and result data")
    print("  - get_box_score() - Detailed game box scores")
    print("  - get_team_stats() - Comprehensive team statistics")
    print("  - get_team_game_log() - Team game-by-game results")
    print("\nAdvantages of nba_api:")
    print("  - Official NBA.com data source")
    print("  - Real-time statistics")
    print("  - More detailed play-by-play and tracking data")
    print("  - Shot chart and location data")
    print("  - No scraping needed - uses official API")
    print("=" * 60)


if __name__ == "__main__":
    main()
