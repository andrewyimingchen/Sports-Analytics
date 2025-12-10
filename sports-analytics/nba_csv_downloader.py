"""
Basketball Reference CSV Data Downloader
This script downloads data using Basketball Reference's CSV export feature
This is more efficient and respectful than HTML scraping
"""

import requests
import pandas as pd
import time
import os
from datetime import datetime
import logging
from urllib.parse import quote

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class NBACSVDownloader:
    def __init__(self, delay=2):
        """
        Initialize the Basketball Reference CSV downloader
        
        Args:
            delay (int): Delay in seconds between downloads
        """
        self.base_url = "https://www.basketball-reference.com"
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.data_dir = "nba_csv_data"
        self._create_directories()
        self.current_season = 2025
    
    def _create_directories(self):
        """Create directories for storing data"""
        directories = [
            self.data_dir,
            f"{self.data_dir}/players",
            f"{self.data_dir}/teams", 
            f"{self.data_dir}/seasons",
            f"{self.data_dir}/playoffs",
            f"{self.data_dir}/drafts",
            f"{self.data_dir}/advanced",
            f"{self.data_dir}/shooting"
        ]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    def download_csv(self, url, filename, process_html_comment=True):
        """
        Download CSV data from a URL
        
        Args:
            url (str): URL of the CSV file
            filename (str): Name to save the file as
            process_html_comment (bool): Whether to remove HTML comments (Basketball Reference specific)
            
        Returns:
            pd.DataFrame or None: Downloaded data as DataFrame
        """
        try:
            # Basketball Reference pattern: most tables can be exported as CSV
            if '_basic' in url or '.html' in url:
                # Convert HTML URL to CSV export URL
                if '?' in url:
                    csv_url = url.replace('.html', '.html?output=csv')
                else:
                    csv_url = url.replace('.html', '.html?output=csv') if '.html' in url else url + '?output=csv'
            else:
                csv_url = url
            
            logging.info(f"Downloading CSV from: {csv_url}")
            
            # Download the data
            response = self.session.get(csv_url)
            response.raise_for_status()
            
            # Basketball Reference sometimes has HTML comments in their CSV exports
            content = response.text
            if process_html_comment:
                content = content.replace('<!--', '').replace('-->', '')
            
            # Save raw CSV
            filepath = os.path.join(self.data_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Also return as DataFrame
            try:
                df = pd.read_csv(filepath)
                
                # Clean up common Basketball Reference issues
                # Remove rows that are duplicate headers
                if 'Player' in df.columns:
                    df = df[df['Player'] != 'Player']
                if 'Rk' in df.columns:
                    df = df[df['Rk'] != 'Rk']
                
                logging.info(f"Downloaded {len(df)} rows to {filepath}")
            except Exception as e:
                logging.warning(f"Could not parse CSV as DataFrame: {e}")
                df = None
            
            # Respect rate limiting
            time.sleep(self.delay)
            
            return df
            
        except Exception as e:
            logging.error(f"Error downloading CSV from {url}: {e}")
            return None
    
    def get_season_stats(self, season=2024, stat_type='per_game'):
        """
        Download all player statistics for a season
        
        Args:
            season (int): Season year (e.g., 2024 for 2023-24 season)
            stat_type (str): Type of stats (per_game, totals, advanced, shooting, etc.)
            
        Returns:
            pd.DataFrame: Player statistics
        """
        stat_types = {
            'per_game': f'{self.base_url}/leagues/NBA_{season}_per_game.html',
            'totals': f'{self.base_url}/leagues/NBA_{season}_totals.html',
            'per_36': f'{self.base_url}/leagues/NBA_{season}_per_minute.html',
            'per_100_poss': f'{self.base_url}/leagues/NBA_{season}_per_poss.html',
            'advanced': f'{self.base_url}/leagues/NBA_{season}_advanced.html',
            'shooting': f'{self.base_url}/leagues/NBA_{season}_shooting.html',
            'play-by-play': f'{self.base_url}/leagues/NBA_{season}_play-by-play.html',
            'adjusted_shooting': f'{self.base_url}/leagues/NBA_{season}_adj_shooting.html'
        }
        
        if stat_type not in stat_types:
            logging.warning(f"Unknown stat type: {stat_type}")
            return pd.DataFrame()
        
        url = stat_types[stat_type]
        filename = f"seasons/{season}_{stat_type}.csv"
        
        logging.info(f"Downloading {stat_type} stats for {season} season")
        df = self.download_csv(url, filename)
        
        return df if df is not None else pd.DataFrame()
    
    def get_team_stats(self, team_abbr='LAL', season=2024):
        """
        Download comprehensive team statistics
        
        Args:
            team_abbr (str): Team abbreviation (e.g., 'LAL', 'BOS', 'GSW')
            season (int): Season year
            
        Returns:
            dict: Dictionary of DataFrames with different team stats
        """
        team_stats = {}
        
        # Different types of team statistics available
        stat_endpoints = {
            'roster': f'{self.base_url}/teams/{team_abbr}/{season}.html',
            'per_game': f'{self.base_url}/teams/{team_abbr}/{season}.html#per_game',
            'totals': f'{self.base_url}/teams/{team_abbr}/{season}.html#totals',
            'advanced': f'{self.base_url}/teams/{team_abbr}/{season}.html#advanced',
            'shooting': f'{self.base_url}/teams/{team_abbr}/{season}.html#shooting',
            'salaries': f'{self.base_url}/teams/{team_abbr}/{season}.html#salaries'
        }
        
        for stat_name, url in stat_endpoints.items():
            logging.info(f"Downloading {stat_name} for {team_abbr} ({season})")
            filename = f"teams/{team_abbr}_{season}_{stat_name}.csv"
            df = self.download_csv(url, filename)
            if df is not None:
                team_stats[stat_name] = df
        
        return team_stats
    
    def get_player_career_stats(self, player_id):
        """
        Download career statistics for a specific player
        
        Args:
            player_id (str): Basketball Reference player ID (e.g., 'jamesle01' for LeBron James)
            
        Returns:
            dict: Dictionary of DataFrames with player's career stats
        """
        first_letter = player_id[0]
        player_stats = {}
        
        # Different career stat tables
        stat_endpoints = {
            'per_game': f'{self.base_url}/players/{first_letter}/{player_id}.html#per_game',
            'totals': f'{self.base_url}/players/{first_letter}/{player_id}.html#totals',
            'per_36': f'{self.base_url}/players/{first_letter}/{player_id}.html#per_minute',
            'per_100_poss': f'{self.base_url}/players/{first_letter}/{player_id}.html#per_poss',
            'advanced': f'{self.base_url}/players/{first_letter}/{player_id}.html#advanced',
            'playoffs_per_game': f'{self.base_url}/players/{first_letter}/{player_id}.html#playoffs_per_game',
            'playoffs_totals': f'{self.base_url}/players/{first_letter}/{player_id}.html#playoffs_totals',
            'all_star': f'{self.base_url}/players/{first_letter}/{player_id}.html#all_star'
        }
        
        for stat_name, url in stat_endpoints.items():
            logging.info(f"Downloading {stat_name} for player {player_id}")
            filename = f"players/{player_id}_{stat_name}.csv"
            df = self.download_csv(url, filename)
            if df is not None:
                player_stats[stat_name] = df
        
        return player_stats
    
    def get_player_game_logs(self, player_id, season=2024, playoffs=False):
        """
        Download game-by-game logs for a player
        
        Args:
            player_id (str): Basketball Reference player ID
            season (int): Season year
            playoffs (bool): Whether to get playoff game logs
            
        Returns:
            pd.DataFrame: Game log data
        """
        first_letter = player_id[0]
        
        if playoffs:
            url = f'{self.base_url}/players/{first_letter}/{player_id}/gamelog/{season}#pgl_basic_playoffs'
            filename = f"players/{player_id}_{season}_playoff_gamelog.csv"
        else:
            url = f'{self.base_url}/players/{first_letter}/{player_id}/gamelog/{season}'
            filename = f"players/{player_id}_{season}_gamelog.csv"
        
        logging.info(f"Downloading {'playoff' if playoffs else 'regular season'} game logs for {player_id} ({season})")
        df = self.download_csv(url, filename)
        
        return df if df is not None else pd.DataFrame()
    
    def get_playoff_stats(self, season=2024):
        """
        Download playoff statistics for a season
        
        Args:
            season (int): Season year
            
        Returns:
            dict: Dictionary of playoff DataFrames
        """
        playoff_stats = {}
        
        stat_types = {
            'per_game': f'{self.base_url}/playoffs/NBA_{season}_per_game.html',
            'totals': f'{self.base_url}/playoffs/NBA_{season}_totals.html',
            'advanced': f'{self.base_url}/playoffs/NBA_{season}_advanced.html',
            'shooting': f'{self.base_url}/playoffs/NBA_{season}_shooting.html'
        }
        
        for stat_name, url in stat_types.items():
            logging.info(f"Downloading playoff {stat_name} for {season}")
            filename = f"playoffs/{season}_{stat_name}.csv"
            df = self.download_csv(url, filename)
            if df is not None:
                playoff_stats[stat_name] = df
        
        return playoff_stats
    
    def get_draft_data(self, year=2024):
        """
        Download NBA draft data for a specific year
        
        Args:
            year (int): Draft year
            
        Returns:
            pd.DataFrame: Draft data
        """
        url = f'{self.base_url}/draft/NBA_{year}.html'
        filename = f"drafts/draft_{year}.csv"
        
        logging.info(f"Downloading {year} NBA Draft data")
        df = self.download_csv(url, filename)
        
        return df if df is not None else pd.DataFrame()
    
    def get_standings(self, season=2024):
        """
        Download NBA standings for a season
        
        Args:
            season (int): Season year
            
        Returns:
            dict: Eastern and Western conference standings
        """
        standings = {}
        
        # Eastern Conference
        east_url = f'{self.base_url}/leagues/NBA_{season}_standings.html#standings_e'
        east_df = self.download_csv(east_url, f"seasons/{season}_standings_east.csv")
        if east_df is not None:
            standings['eastern'] = east_df
        
        # Western Conference  
        west_url = f'{self.base_url}/leagues/NBA_{season}_standings.html#standings_w'
        west_df = self.download_csv(west_url, f"seasons/{season}_standings_west.csv")
        if west_df is not None:
            standings['western'] = west_df
        
        return standings
    
    def bulk_download_season(self, season=2024):
        """
        Download comprehensive data for an entire season
        
        Args:
            season (int): Season year
            
        Returns:
            dict: Dictionary containing all season data
        """
        logging.info(f"Starting bulk download for {season} season")
        
        season_data = {
            'season': season,
            'download_time': datetime.now().isoformat()
        }
        
        # Download various statistics
        logging.info("Downloading regular season statistics...")
        season_data['per_game'] = self.get_season_stats(season, 'per_game')
        season_data['totals'] = self.get_season_stats(season, 'totals')
        season_data['advanced'] = self.get_season_stats(season, 'advanced')
        season_data['shooting'] = self.get_season_stats(season, 'shooting')
        
        # Download standings
        logging.info("Downloading standings...")
        season_data['standings'] = self.get_standings(season)
        
        # Download playoff stats if available
        logging.info("Downloading playoff statistics...")
        season_data['playoffs'] = self.get_playoff_stats(season)
        
        # Download draft data
        logging.info("Downloading draft data...")
        season_data['draft'] = self.get_draft_data(season)
        
        logging.info(f"Bulk download complete for {season} season")
        return season_data
    
    def get_top_players_detailed(self, season=2024, num_players=10):
        """
        Get detailed stats for top players by points per game
        
        Args:
            season (int): Season year
            num_players (int): Number of top players to get
            
        Returns:
            list: List of player data dictionaries
        """
        # First get season stats to identify top players
        season_stats = self.get_season_stats(season, 'per_game')
        
        if season_stats.empty:
            logging.error("Could not fetch season statistics")
            return []
        
        # Clean and sort by points
        if 'PTS' in season_stats.columns:
            season_stats['PTS'] = pd.to_numeric(season_stats['PTS'], errors='coerce')
            season_stats = season_stats.dropna(subset=['PTS'])
            top_players = season_stats.nlargest(num_players, 'PTS')
        else:
            top_players = season_stats.head(num_players)
        
        top_players_data = []
        
        # Common player IDs mapping (you would need to expand this)
        player_id_mapping = {
            'Luka Dončić': 'doncilu01',
            'Giannis Antetokounmpo': 'antetgi01',
            'Joel Embiid': 'embiijo01',
            'Jayson Tatum': 'tatumja01',
            'Stephen Curry': 'curryst01',
            'Kevin Durant': 'duranke01',
            'LeBron James': 'jamesle01',
            'Nikola Jokić': 'jokicni01',
            'Damian Lillard': 'lillada01',
            'Donovan Mitchell': 'mitchdo01'
        }
        
        for idx, player_row in top_players.iterrows():
            player_name = player_row.get('Player', 'Unknown')
            
            player_data = {
                'name': player_name,
                'season_stats': player_row.to_dict()
            }
            
            # If we have the player ID, get their detailed stats
            if player_name in player_id_mapping:
                player_id = player_id_mapping[player_name]
                logging.info(f"Getting detailed stats for {player_name}")
                
                # Get career stats
                career_stats = self.get_player_career_stats(player_id)
                player_data['career_stats'] = {k: v.to_dict('records') if isinstance(v, pd.DataFrame) else v 
                                              for k, v in career_stats.items()}
                
                # Get game logs
                game_logs = self.get_player_game_logs(player_id, season)
                if not game_logs.empty:
                    player_data['game_logs'] = game_logs.to_dict('records')
            
            top_players_data.append(player_data)
        
        return top_players_data


def main():
    """
    Main function demonstrating CSV downloader usage
    """
    print("Basketball Reference CSV Data Downloader")
    print("=" * 50)
    print("\nThis downloader uses Basketball Reference's CSV export feature")
    print("Please ensure compliance with their Terms of Service\n")
    
    # Initialize downloader
    downloader = NBACSVDownloader(delay=2)
    
    print("Download Options:")
    print("1. Current season statistics (all players)")
    print("2. Team statistics")
    print("3. Player career statistics")
    print("4. Playoff statistics")
    print("5. Draft data")
    print("6. Complete season bulk download")
    
    # Example 1: Download current season stats
    print("\n" + "="*50)
    print("Example 1: Downloading 2023-24 season per game statistics...")
    season_stats = downloader.get_season_stats(2024, 'per_game')
    if not season_stats.empty:
        print(f"Downloaded stats for {len(season_stats)} players")
        print(f"Top 5 scorers:")
        if 'PTS' in season_stats.columns:
            season_stats['PTS'] = pd.to_numeric(season_stats['PTS'], errors='coerce')
            top_scorers = season_stats.nlargest(5, 'PTS')[['Player', 'Team', 'G', 'PTS']]
            print(top_scorers.to_string(index=False))
    
    # Example 2: Download team stats
    print("\n" + "="*50)
    print("Example 2: Downloading Lakers 2023-24 season statistics...")
    lakers_stats = downloader.get_team_stats('LAL', 2024)
    for stat_type, df in lakers_stats.items():
        if isinstance(df, pd.DataFrame):
            print(f"  - {stat_type}: {len(df)} rows")
    
    # Example 3: Download player career stats
    print("\n" + "="*50)
    print("Example 3: Downloading LeBron James career statistics...")
    lebron_stats = downloader.get_player_career_stats('jamesle01')
    for stat_type, df in lebron_stats.items():
        if isinstance(df, pd.DataFrame):
            print(f"  - {stat_type}: {len(df)} seasons")
    
    # Example 4: Download playoff stats
    print("\n" + "="*50)
    print("Example 4: Downloading 2023-24 playoff statistics...")
    playoff_stats = downloader.get_playoff_stats(2024)
    for stat_type, df in playoff_stats.items():
        if isinstance(df, pd.DataFrame):
            print(f"  - {stat_type}: {len(df)} players")
    
    # Example 5: Get top players with detailed stats
    print("\n" + "="*50)
    print("Example 5: Getting top 5 players with detailed stats...")
    top_players = downloader.get_top_players_detailed(2024, num_players=5)
    for player in top_players:
        print(f"  - {player['name']}: {player['season_stats'].get('PTS', 'N/A')} PPG")
    
    print(f"\n" + "="*50)
    print(f"All data saved in '{downloader.data_dir}' directory")
    print("\nYou can extend this downloader to:")
    print("- Download historical seasons (change season parameter)")
    print("- Get specific player game logs")
    print("- Download combine and summer league data")
    print("- Extract coaching and referee statistics")
    print("\nRemember to respect rate limits and Terms of Service!")


if __name__ == "__main__":
    main()