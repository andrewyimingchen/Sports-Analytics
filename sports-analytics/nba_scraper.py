"""
Basketball Reference NBA Statistics Scraper
This script uses the basketball_reference_web_scraper library to fetch NBA statistics
Much cleaner and more reliable than manual HTML scraping
"""

from basketball_reference_web_scraper import client
from basketball_reference_web_scraper.data import OutputType, Team
import pandas as pd
import os
import json
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('nba_scraper.log'),
        logging.StreamHandler()
    ]
)

class NBAReferenceScraper:
    def __init__(self):
        """
        Initialize the Basketball Reference scraper using the official library
        Much simpler than manual scraping!
        """
        self.data_dir = "nba_data"
        self._create_directories()
        self.current_season = 2025  # Update this as needed
    
    def _create_directories(self):
        """Create directories for storing scraped data"""
        directories = [
            self.data_dir,
            f"{self.data_dir}/players",
            f"{self.data_dir}/teams",
            f"{self.data_dir}/seasons",
            f"{self.data_dir}/games",
            f"{self.data_dir}/box_scores",
            f"{self.data_dir}/play_by_play"
        ]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    def get_player_box_scores(self, day, month, year):
        """
        Get player box scores for all games on a specific date

        Args:
            day (int): Day of the month
            month (int): Month (1-12)
            year (int): Year

        Returns:
            list: List of player box score dictionaries
        """
        try:
            logging.info(f"Fetching player box scores for {year}-{month:02d}-{day:02d}")
            box_scores = client.player_box_scores(day=day, month=month, year=year)
            logging.info(f"Retrieved {len(box_scores)} player box scores")
            return box_scores
        except Exception as e:
            logging.error(f"Error fetching player box scores: {e}")
            return []

    def get_team_box_scores(self, day, month, year):
        """
        Get team box scores for all games on a specific date

        Args:
            day (int): Day of the month
            month (int): Month (1-12)
            year (int): Year

        Returns:
            list: List of team box score dictionaries
        """
        try:
            logging.info(f"Fetching team box scores for {year}-{month:02d}-{day:02d}")
            box_scores = client.team_box_scores(day=day, month=month, year=year)
            logging.info(f"Retrieved {len(box_scores)} team box scores")
            return box_scores
        except Exception as e:
            logging.error(f"Error fetching team box scores: {e}")
            return []
    
    def get_regular_season_player_box_scores(self, player_identifier, season_end_year):
        """
        Get all regular season game box scores for a specific player

        Args:
            player_identifier (str): Basketball Reference player identifier (e.g., 'jamesle01')
            season_end_year (int): The year the season ended (e.g., 2024 for 2023-24 season)

        Returns:
            list: List of game box score dictionaries
        """
        try:
            logging.info(f"Fetching regular season box scores for {player_identifier} ({season_end_year})")
            box_scores = client.regular_season_player_box_scores(
                player_identifier=player_identifier,
                season_end_year=season_end_year
            )
            logging.info(f"Retrieved {len(box_scores)} regular season games")
            return box_scores
        except Exception as e:
            logging.error(f"Error fetching player box scores: {e}")
            return []

    def get_playoff_player_box_scores(self, player_identifier, season_end_year):
        """
        Get all playoff game box scores for a specific player

        Args:
            player_identifier (str): Basketball Reference player identifier (e.g., 'jamesle01')
            season_end_year (int): The year the season ended (e.g., 2024 for 2023-24 season)

        Returns:
            list: List of playoff game box score dictionaries
        """
        try:
            logging.info(f"Fetching playoff box scores for {player_identifier} ({season_end_year})")
            box_scores = client.playoff_player_box_scores(
                player_identifier=player_identifier,
                season_end_year=season_end_year
            )
            logging.info(f"Retrieved {len(box_scores)} playoff games")
            return box_scores
        except Exception as e:
            logging.error(f"Error fetching playoff box scores: {e}")
            return []
    
    def get_season_schedule(self, season_end_year):
        """
        Get the complete schedule for an NBA season

        Args:
            season_end_year (int): The year the season ended (e.g., 2024 for 2023-24 season)

        Returns:
            list: List of scheduled game dictionaries
        """
        try:
            logging.info(f"Fetching season schedule for {season_end_year}")
            schedule = client.season_schedule(season_end_year=season_end_year)
            logging.info(f"Retrieved {len(schedule)} scheduled games")
            return schedule
        except Exception as e:
            logging.error(f"Error fetching season schedule: {e}")
            return []
    
    def get_players_season_totals(self, season_end_year):
        """
        Get season total statistics for all players (basic stats)

        Args:
            season_end_year (int): The year the season ended (e.g., 2024 for 2023-24 season)

        Returns:
            list: List of player season total dictionaries
        """
        try:
            logging.info(f"Fetching player season totals for {season_end_year}")
            totals = client.players_season_totals(season_end_year=season_end_year)
            logging.info(f"Retrieved season totals for {len(totals)} players")
            return totals
        except Exception as e:
            logging.error(f"Error fetching player season totals: {e}")
            return []

    def get_players_advanced_season_totals(self, season_end_year):
        """
        Get advanced season statistics for all players

        Args:
            season_end_year (int): The year the season ended (e.g., 2024 for 2023-24 season)

        Returns:
            list: List of player advanced stats dictionaries
        """
        try:
            logging.info(f"Fetching advanced season totals for {season_end_year}")
            advanced = client.players_advanced_season_totals(season_end_year=season_end_year)
            logging.info(f"Retrieved advanced stats for {len(advanced)} players")
            return advanced
        except Exception as e:
            logging.error(f"Error fetching advanced season totals: {e}")
            return []
    
    def get_play_by_play(self, home_team, year, month, day):
        """
        Get detailed play-by-play data for a specific game

        Args:
            home_team (Team): Team enum for home team (e.g., Team.BOSTON_CELTICS)
            year (int): Year of the game
            month (int): Month (1-12)
            day (int): Day of the month

        Returns:
            list: List of play-by-play event dictionaries
        """
        try:
            logging.info(f"Fetching play-by-play for {home_team.name} on {year}-{month:02d}-{day:02d}")
            pbp = client.play_by_play(home_team=home_team, year=year, month=month, day=day)
            logging.info(f"Retrieved {len(pbp)} play-by-play events")
            return pbp
        except Exception as e:
            logging.error(f"Error fetching play-by-play: {e}")
            return []

    def search_players(self, term):
        """
        Search for players by name

        Args:
            term (str): Search term (player name or partial name)

        Returns:
            list: List of search result dictionaries
        """
        try:
            logging.info(f"Searching for players: '{term}'")
            results = client.search(term=term)
            logging.info(f"Found {len(results)} search results")
            return results
        except Exception as e:
            logging.error(f"Error searching players: {e}")
            return []

    def get_standings(self, season_end_year):
        """
        Get league standings for a season

        Args:
            season_end_year (int): The year the season ended (e.g., 2024 for 2023-24 season)

        Returns:
            list: List of team standings dictionaries
        """
        try:
            logging.info(f"Fetching standings for {season_end_year}")
            standings = client.standings(season_end_year=season_end_year)
            logging.info(f"Retrieved standings for {len(standings)} teams")
            return standings
        except Exception as e:
            logging.error(f"Error fetching standings: {e}")
            return []
    
    
    def save_data(self, data, filename, data_type='json'):
        """
        Save scraped data to file

        Args:
            data: Data to save (list of dicts or pandas DataFrame)
            filename (str): Name of the file (without extension)
            data_type (str): Type of file ('json' or 'csv')
        """
        if data_type == 'json':
            filepath = f"{self.data_dir}/{filename}.json"
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            logging.info(f"Data saved to {filepath}")
        elif data_type == 'csv':
            filepath = f"{self.data_dir}/{filename}.csv"
            # Convert list of dicts to DataFrame if needed
            if isinstance(data, list):
                df = pd.DataFrame(data)
            else:
                df = data
            df.to_csv(filepath, index=False)
            logging.info(f"Data saved to {filepath}")


def main():
    """
    Main function to demonstrate usage of the NBA scraper using the official library
    """
    # Initialize scraper (no delay needed - library handles it!)
    scraper = NBAReferenceScraper()

    print("Basketball Reference NBA Statistics Scraper")
    print("=" * 60)
    print("Using the official basketball_reference_web_scraper library")
    print("=" * 60)

    # Example 1: Get player box scores for a specific date
    print("\nExample 1: Player box scores for January 15, 2024")
    player_scores = scraper.get_player_box_scores(day=15, month=1, year=2024)
    if player_scores:
        print(f"Retrieved {len(player_scores)} player performances")
        # Show first 5
        for i, score in enumerate(player_scores[:5], 1):
            print(f"  {i}. {score.get('name', 'N/A')} - {score.get('points', 0)} pts")
        scraper.save_data(player_scores, "box_scores/20240115_players", 'json')

    # Example 2: Get season totals for all players
    print("\nExample 2: Season totals for 2023-24")
    season_totals = scraper.get_players_season_totals(season_end_year=2024)
    if season_totals:
        print(f"Retrieved stats for {len(season_totals)} players")
        scraper.save_data(season_totals, "seasons/2024_season_totals", 'csv')

    # Example 3: Get advanced stats
    print("\nExample 3: Advanced stats for 2023-24")
    advanced_stats = scraper.get_players_advanced_season_totals(season_end_year=2024)
    if advanced_stats:
        print(f"Retrieved advanced stats for {len(advanced_stats)} players")
        scraper.save_data(advanced_stats, "seasons/2024_advanced_stats", 'csv')

    # Example 4: Search for a specific player
    print("\nExample 4: Searching for LeBron James")
    search_results = scraper.search_players(term="LeBron")
    if search_results:
        print(f"Found {len(search_results)} results")
        for result in search_results[:3]:
            print(f"  - {result.get('name', 'N/A')}")

    # Example 5: Get standings
    print("\nExample 5: League standings for 2023-24")
    standings = scraper.get_standings(season_end_year=2024)
    if standings:
        print(f"Retrieved standings for {len(standings)} teams")
        # Show top 5 teams
        for i, team in enumerate(standings[:5], 1):
            print(f"  {i}. {team.get('team', 'N/A')} - "
                  f"{team.get('wins', 0)}-{team.get('losses', 0)}")
        scraper.save_data(standings, "seasons/2024_standings", 'json')

    # Example 6: Get individual player game logs
    print("\nExample 6: LeBron James regular season games (2023-24)")
    # Player identifier can be found via search or from basketball-reference URLs
    lebron_games = scraper.get_regular_season_player_box_scores(
        player_identifier="jamesle01",
        season_end_year=2024
    )
    if lebron_games:
        print(f"Retrieved {len(lebron_games)} games")
        scraper.save_data(lebron_games, "players/lebron_james_2024", 'json')

    print(f"\nAll data saved in '{scraper.data_dir}' directory")
    print("\n" + "=" * 60)
    print("Additional capabilities:")
    print("  - get_team_box_scores() - Team stats for specific dates")
    print("  - get_season_schedule() - Full season schedule")
    print("  - get_playoff_player_box_scores() - Playoff game logs")
    print("  - get_play_by_play() - Detailed play-by-play data")
    print("\nAdvantages of using this library:")
    print("  - No HTML parsing required")
    print("  - Built-in error handling")
    print("  - Cleaner, more maintainable code")
    print("  - Less prone to breaking when site changes")
    print("=" * 60)


if __name__ == "__main__":
    main()