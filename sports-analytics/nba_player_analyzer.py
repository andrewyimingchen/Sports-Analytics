"""
NBA Player Statistics Analyzer
Advanced tool for downloading and analyzing NBA player statistics
Includes comparison tools, trend analysis, and visualization preparation
"""

import requests
import pandas as pd
import numpy as np
import time
import os
import json
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class NBAPlayerAnalyzer:
    def __init__(self, delay=2):
        """
        Initialize the NBA Player Analyzer
        
        Args:
            delay (int): Delay in seconds between requests
        """
        self.base_url = "https://www.basketball-reference.com"
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.data_dir = "nba_analysis"
        self._create_directories()
        self.current_season = 2025
        
        # Player ID mapping (expand as needed)
        self.player_ids = {
            'LeBron James': 'jamesle01',
            'Stephen Curry': 'curryst01',
            'Kevin Durant': 'duranke01',
            'Giannis Antetokounmpo': 'antetgi01',
            'Nikola Jokić': 'jokicni01',
            'Luka Dončić': 'doncilu01',
            'Joel Embiid': 'embiijo01',
            'Jayson Tatum': 'tatumja01',
            'Damian Lillard': 'lillada01',
            'Jimmy Butler': 'butleji01',
            'Kawhi Leonard': 'leonaka01',
            'Paul George': 'georgpa01',
            'Anthony Davis': 'davisat02',
            'Devin Booker': 'bookede01',
            'Trae Young': 'youngtr01',
            'Ja Morant': 'moranja01',
            'Zion Williamson': 'willizi01',
            'Karl-Anthony Towns': 'townska01',
            'Jaylen Brown': 'brownja02',
            'Donovan Mitchell': 'mitchdo01'
        }
    
    def _create_directories(self):
        """Create directories for storing data"""
        directories = [
            self.data_dir,
            f"{self.data_dir}/players",
            f"{self.data_dir}/comparisons",
            f"{self.data_dir}/trends",
            f"{self.data_dir}/reports",
            f"{self.data_dir}/cache"
        ]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    def _download_data(self, url: str) -> Optional[pd.DataFrame]:
        """
        Download data from Basketball Reference
        
        Args:
            url (str): URL to download from
            
        Returns:
            pd.DataFrame or None: Downloaded data
        """
        try:
            # Add CSV export parameter
            csv_url = url + ('&output=csv' if '?' in url else '?output=csv')
            
            logging.info(f"Downloading: {csv_url}")
            response = self.session.get(csv_url)
            response.raise_for_status()
            
            # Parse CSV
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            
            # Clean up duplicate headers
            if 'Player' in df.columns:
                df = df[df['Player'] != 'Player']
            if 'Season' in df.columns:
                df = df[df['Season'] != 'Season']
            
            time.sleep(self.delay)
            return df
            
        except Exception as e:
            logging.error(f"Error downloading data: {e}")
            return None
    
    def get_player_career_stats(self, player_name: str) -> Dict:
        """
        Get comprehensive career statistics for a player
        
        Args:
            player_name (str): Name of the player
            
        Returns:
            dict: Career statistics
        """
        if player_name not in self.player_ids:
            logging.warning(f"Player ID not found for {player_name}")
            return {}
        
        player_id = self.player_ids[player_name]
        first_letter = player_id[0]
        
        career_data = {
            'player_name': player_name,
            'player_id': player_id,
            'retrieved_at': datetime.now().isoformat()
        }
        
        # URLs for different stat types
        stat_urls = {
            'per_game': f'{self.base_url}/players/{first_letter}/{player_id}.html#per_game',
            'totals': f'{self.base_url}/players/{first_letter}/{player_id}.html#totals',
            'per_36': f'{self.base_url}/players/{first_letter}/{player_id}.html#per_minute',
            'advanced': f'{self.base_url}/players/{first_letter}/{player_id}.html#advanced',
            'playoffs_per_game': f'{self.base_url}/players/{first_letter}/{player_id}.html#playoffs_per_game',
            'playoffs_totals': f'{self.base_url}/players/{first_letter}/{player_id}.html#playoffs_totals'
        }
        
        for stat_type, url in stat_urls.items():
            df = self._download_data(url)
            if df is not None and not df.empty:
                career_data[stat_type] = df.to_dict('records')
                logging.info(f"Retrieved {stat_type} for {player_name}: {len(df)} seasons")
        
        return career_data
    
    def compare_players(self, player_names: List[str], season: int = None, stat_types: List[str] = None) -> pd.DataFrame:
        """
        Compare multiple players across various statistics
        
        Args:
            player_names (list): List of player names to compare
            season (int): Season to compare (None for career averages)
            stat_types (list): Statistics to compare
            
        Returns:
            pd.DataFrame: Comparison table
        """
        if season is None:
            season = self.current_season - 1
        
        if stat_types is None:
            stat_types = ['PTS', 'TRB', 'AST', 'FG%', 'FT%', '3P%', 'PER', 'WS']
        
        comparison_data = []
        
        # Get season stats for comparison
        season_stats_url = f'{self.base_url}/leagues/NBA_{season}_per_game.html'
        season_df = self._download_data(season_stats_url)
        
        if season_df is None:
            logging.error("Could not retrieve season statistics")
            return pd.DataFrame()
        
        # Get advanced stats
        advanced_url = f'{self.base_url}/leagues/NBA_{season}_advanced.html'
        advanced_df = self._download_data(advanced_url)
        
        for player_name in player_names:
            player_row = {}
            player_row['Player'] = player_name
            
            # Find player in season stats
            player_basic = season_df[season_df['Player'].str.contains(player_name, case=False, na=False)]
            if not player_basic.empty:
                player_basic = player_basic.iloc[0]
                for stat in stat_types:
                    if stat in player_basic.index:
                        player_row[stat] = player_basic[stat]
            
            # Find player in advanced stats
            if advanced_df is not None:
                player_advanced = advanced_df[advanced_df['Player'].str.contains(player_name, case=False, na=False)]
                if not player_advanced.empty:
                    player_advanced = player_advanced.iloc[0]
                    for stat in ['PER', 'TS%', 'WS', 'BPM', 'VORP']:
                        if stat in player_advanced.index and stat in stat_types:
                            player_row[stat] = player_advanced[stat]
            
            comparison_data.append(player_row)
        
        comparison_df = pd.DataFrame(comparison_data)
        
        # Convert numeric columns
        numeric_cols = [col for col in comparison_df.columns if col != 'Player']
        for col in numeric_cols:
            comparison_df[col] = pd.to_numeric(comparison_df[col], errors='coerce')
        
        return comparison_df
    
    def analyze_player_trends(self, player_name: str, stat: str = 'PTS', num_games: int = 10) -> Dict:
        """
        Analyze recent performance trends for a player
        
        Args:
            player_name (str): Name of the player
            stat (str): Statistic to analyze
            num_games (int): Number of recent games to analyze
            
        Returns:
            dict: Trend analysis results
        """
        if player_name not in self.player_ids:
            logging.warning(f"Player ID not found for {player_name}")
            return {}
        
        player_id = self.player_ids[player_name]
        first_letter = player_id[0]
        
        # Get current season game logs
        gamelog_url = f'{self.base_url}/players/{first_letter}/{player_id}/gamelog/{self.current_season}'
        gamelog_df = self._download_data(gamelog_url)
        
        if gamelog_df is None or gamelog_df.empty:
            logging.error(f"Could not retrieve game logs for {player_name}")
            return {}
        
        # Filter to most recent games
        gamelog_df = gamelog_df.head(num_games)
        
        # Convert stat column to numeric
        if stat in gamelog_df.columns:
            gamelog_df[stat] = pd.to_numeric(gamelog_df[stat], errors='coerce')
            
            # Calculate trends
            trends = {
                'player': player_name,
                'stat': stat,
                'num_games': len(gamelog_df),
                'average': gamelog_df[stat].mean(),
                'median': gamelog_df[stat].median(),
                'std_dev': gamelog_df[stat].std(),
                'min': gamelog_df[stat].min(),
                'max': gamelog_df[stat].max(),
                'trend': 'increasing' if gamelog_df[stat].iloc[0] > gamelog_df[stat].iloc[-1] else 'decreasing',
                'last_5_avg': gamelog_df[stat].head(5).mean(),
                'last_10_avg': gamelog_df[stat].head(10).mean() if len(gamelog_df) >= 10 else gamelog_df[stat].mean(),
                'games_data': gamelog_df[['Date', 'Opp', stat]].to_dict('records')
            }
            
            # Calculate moving average
            if len(gamelog_df) >= 3:
                gamelog_df['MA3'] = gamelog_df[stat].rolling(window=3).mean()
                trends['moving_avg_3'] = gamelog_df['MA3'].iloc[-1]
            
            return trends
        
        return {}
    
    def get_head_to_head(self, player1: str, player2: str, season: int = None) -> Dict:
        """
        Get head-to-head comparison between two players
        
        Args:
            player1 (str): First player name
            player2 (str): Second player name
            season (int): Season for comparison
            
        Returns:
            dict: Head-to-head statistics
        """
        if season is None:
            season = self.current_season - 1
        
        comparison = self.compare_players([player1, player2], season)
        
        if comparison.empty:
            return {}
        
        h2h_data = {
            'season': season,
            'players': [player1, player2],
            'comparison': comparison.to_dict('records'),
            'winner': {}
        }
        
        # Determine "winner" for each stat
        numeric_cols = [col for col in comparison.columns if col != 'Player']
        for col in numeric_cols:
            values = comparison[col].values
            if len(values) == 2 and not pd.isna(values).all():
                if values[0] > values[1]:
                    h2h_data['winner'][col] = player1
                elif values[1] > values[0]:
                    h2h_data['winner'][col] = player2
                else:
                    h2h_data['winner'][col] = 'tie'
        
        return h2h_data
    
    def generate_player_report(self, player_name: str, season: int = None) -> Dict:
        """
        Generate comprehensive player report
        
        Args:
            player_name (str): Player name
            season (int): Season for report
            
        Returns:
            dict: Comprehensive player report
        """
        if season is None:
            season = self.current_season - 1
        
        logging.info(f"Generating comprehensive report for {player_name}")
        
        report = {
            'player_name': player_name,
            'season': season,
            'generated_at': datetime.now().isoformat(),
            'sections': {}
        }
        
        # Get career statistics
        career_stats = self.get_player_career_stats(player_name)
        if career_stats:
            report['sections']['career_overview'] = career_stats
        
        # Get current season trends
        for stat in ['PTS', 'AST', 'TRB']:
            trend = self.analyze_player_trends(player_name, stat, num_games=10)
            if trend:
                report['sections'][f'{stat.lower()}_trend'] = trend
        
        # Get comparison with top players
        top_players = ['LeBron James', 'Kevin Durant', 'Stephen Curry', 'Giannis Antetokounmpo']
        if player_name not in top_players:
            top_players.append(player_name)
        
        comparison = self.compare_players(top_players, season)
        if not comparison.empty:
            report['sections']['peer_comparison'] = comparison.to_dict('records')
        
        # Calculate percentile rankings
        season_stats_url = f'{self.base_url}/leagues/NBA_{season}_per_game.html'
        all_players_df = self._download_data(season_stats_url)
        
        if all_players_df is not None:
            player_stats = all_players_df[all_players_df['Player'].str.contains(player_name, case=False, na=False)]
            if not player_stats.empty:
                player_stats = player_stats.iloc[0]
                percentiles = {}
                
                for stat in ['PTS', 'AST', 'TRB', 'STL', 'BLK']:
                    if stat in all_players_df.columns:
                        all_players_df[stat] = pd.to_numeric(all_players_df[stat], errors='coerce')
                        stat_value = pd.to_numeric(player_stats[stat], errors='coerce')
                        if not pd.isna(stat_value):
                            percentile = (all_players_df[stat] < stat_value).mean() * 100
                            percentiles[stat] = {
                                'value': stat_value,
                                'percentile': round(percentile, 1)
                            }
                
                report['sections']['percentile_rankings'] = percentiles
        
        return report
    
    def bulk_download_top_players(self, num_players: int = 50, season: int = None) -> List[Dict]:
        """
        Download and analyze top players by various metrics
        
        Args:
            num_players (int): Number of top players to analyze
            season (int): Season year
            
        Returns:
            list: List of player analysis dictionaries
        """
        if season is None:
            season = self.current_season - 1
        
        logging.info(f"Analyzing top {num_players} players for {season} season")
        
        # Get season statistics
        season_stats_url = f'{self.base_url}/leagues/NBA_{season}_per_game.html'
        season_df = self._download_data(season_stats_url)
        
        if season_df is None or season_df.empty:
            logging.error("Could not retrieve season statistics")
            return []
        
        # Clean and sort by points
        season_df['PTS'] = pd.to_numeric(season_df['PTS'], errors='coerce')
        season_df = season_df.dropna(subset=['PTS'])
        top_scorers = season_df.nlargest(num_players, 'PTS')
        
        players_analysis = []
        
        for idx, player_row in top_scorers.iterrows():
            player_name = player_row['Player']
            
            player_analysis = {
                'rank': len(players_analysis) + 1,
                'player': player_name,
                'team': player_row.get('Tm', 'Unknown'),
                'basic_stats': {
                    'games': player_row.get('G', 0),
                    'ppg': player_row.get('PTS', 0),
                    'apg': player_row.get('AST', 0),
                    'rpg': player_row.get('TRB', 0),
                    'fg_pct': player_row.get('FG%', 0),
                    'three_pct': player_row.get('3P%', 0),
                    'ft_pct': player_row.get('FT%', 0)
                }
            }
            
            # Get trends if player ID is available
            if player_name in self.player_ids:
                trend = self.analyze_player_trends(player_name, 'PTS', num_games=5)
                if trend:
                    player_analysis['recent_trend'] = {
                        'last_5_games': trend.get('last_5_avg', 0),
                        'season_avg': trend.get('average', 0),
                        'direction': trend.get('trend', 'stable')
                    }
            
            players_analysis.append(player_analysis)
        
        return players_analysis
    
    def save_report(self, data: Dict, filename: str, format: str = 'json'):
        """
        Save analysis report to file
        
        Args:
            data (dict): Report data
            filename (str): Filename (without extension)
            format (str): File format ('json' or 'csv')
        """
        if format == 'json':
            filepath = f"{self.data_dir}/reports/{filename}.json"
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            logging.info(f"Report saved to {filepath}")
        elif format == 'csv' and isinstance(data, pd.DataFrame):
            filepath = f"{self.data_dir}/reports/{filename}.csv"
            data.to_csv(filepath, index=False)
            logging.info(f"Report saved to {filepath}")


def main():
    """
    Main function demonstrating the NBA Player Analyzer
    """
    print("NBA Player Statistics Analyzer")
    print("=" * 50)
    print("\nAdvanced tool for analyzing NBA player statistics")
    print("Please ensure compliance with Basketball Reference Terms of Service\n")
    
    # Initialize analyzer
    analyzer = NBAPlayerAnalyzer(delay=2)
    
    print("Analysis Options:")
    print("1. Player Career Statistics")
    print("2. Player Performance Trends")
    print("3. Head-to-Head Comparisons")
    print("4. Top Players Analysis")
    print("5. Comprehensive Player Report")
    
    # Example 1: Get career stats for a star player
    print("\n" + "="*50)
    print("Example 1: Analyzing LeBron James career statistics...")
    lebron_stats = analyzer.get_player_career_stats('LeBron James')
    if lebron_stats:
        print(f"Retrieved career data for LeBron James")
        if 'per_game' in lebron_stats:
            print(f"  - Regular season: {len(lebron_stats['per_game'])} seasons")
        if 'playoffs_per_game' in lebron_stats:
            print(f"  - Playoffs: {len(lebron_stats['playoffs_per_game'])} seasons")
        analyzer.save_report(lebron_stats, 'lebron_career', 'json')
    
    # Example 2: Compare multiple players
    print("\n" + "="*50)
    print("Example 2: Comparing top NBA players...")
    comparison = analyzer.compare_players(
        ['LeBron James', 'Kevin Durant', 'Stephen Curry', 'Giannis Antetokounmpo'],
        season=2024
    )
    if not comparison.empty:
        print("\n2023-24 Season Comparison:")
        print(comparison[['Player', 'PTS', 'AST', 'TRB']].to_string(index=False))
        analyzer.save_report(comparison, 'top_players_comparison', 'csv')
    
    # Example 3: Analyze player trends
    print("\n" + "="*50)
    print("Example 3: Analyzing scoring trends for Stephen Curry...")
    curry_trend = analyzer.analyze_player_trends('Stephen Curry', 'PTS', num_games=10)
    if curry_trend:
        print(f"Stephen Curry - Last 10 games:")
        print(f"  - Average: {curry_trend['average']:.1f} PPG")
        print(f"  - Trend: {curry_trend['trend']}")
        print(f"  - Last 5 games: {curry_trend['last_5_avg']:.1f} PPG")
        analyzer.save_report(curry_trend, 'curry_scoring_trend', 'json')
    
    # Example 4: Head-to-head comparison
    print("\n" + "="*50)
    print("Example 4: Head-to-head comparison...")
    h2h = analyzer.get_head_to_head('LeBron James', 'Kevin Durant', 2024)
    if h2h:
        print(f"\nLeBron James vs Kevin Durant (2023-24):")
        for stat, winner in h2h['winner'].items():
            print(f"  - {stat}: {winner}")
    
    # Example 5: Generate comprehensive player report
    print("\n" + "="*50)
    print("Example 5: Generating comprehensive report for Giannis Antetokounmpo...")
    report = analyzer.generate_player_report('Giannis Antetokounmpo', 2024)
    if report:
        print(f"Generated comprehensive report with {len(report['sections'])} sections")
        if 'percentile_rankings' in report['sections']:
            print("\nPercentile Rankings:")
            for stat, data in report['sections']['percentile_rankings'].items():
                print(f"  - {stat}: {data['value']} ({data['percentile']}th percentile)")
        analyzer.save_report(report, 'giannis_comprehensive_report', 'json')
    
    # Example 6: Analyze top players
    print("\n" + "="*50)
    print("Example 6: Analyzing top 10 scorers...")
    top_players = analyzer.bulk_download_top_players(num_players=10, season=2024)
    if top_players:
        print("\nTop 10 Scorers (2023-24):")
        for player in top_players[:5]:  # Show top 5
            print(f"  {player['rank']}. {player['player']} ({player['team']}): {player['basic_stats']['ppg']} PPG")
        analyzer.save_report({'players': top_players}, 'top_scorers_2024', 'json')
    
    print(f"\n" + "="*50)
    print(f"All analysis reports saved in '{analyzer.data_dir}/reports' directory")
    print("\nYou can extend this analyzer to:")
    print("- Track player performance over time")
    print("- Predict future performance")
    print("- Generate team chemistry analysis")
    print("- Create fantasy basketball insights")
    print("- Build player similarity scores")


if __name__ == "__main__":
    main()