# NBA Basketball Reference Statistics Tools

A comprehensive Python toolkit for downloading and analyzing NBA statistics from Basketball-Reference.com.

## ⚠️ Important Legal Notice

**Before using these tools, you MUST:**
1. Read and comply with Basketball Reference's Terms of Service: https://www.sports-reference.com/termsofuse.html
2. Check their robots.txt file: https://www.basketball-reference.com/robots.txt
3. Respect rate limits and server resources
4. Use the data in accordance with their copyright policies
5. Consider contacting Sports Reference LLC for bulk data access or API options

## 🏀 Tools Included

### 1. **nba_scraper.py** - Comprehensive HTML Scraper
Full-featured web scraper with HTML parsing for detailed data extraction.

**Features:**
- Player career statistics (regular season & playoffs)
- Team rosters and statistics
- Season-wide player rankings
- Game logs and play-by-play data
- Draft data and combine results
- Historical data access

### 2. **nba_csv_downloader.py** - CSV Export Downloader
Efficient tool using Basketball Reference's built-in CSV export feature.

**Features:**
- Faster downloads using CSV exports
- Season statistics (per game, totals, advanced)
- Team statistics and standings
- Player game logs
- Playoff statistics
- Draft data

### 3. **nba_player_analyzer.py** - Advanced Analytics Tool
Sophisticated analysis tool for player performance and comparisons.

**Features:**
- Player trend analysis
- Head-to-head comparisons
- Percentile rankings
- Performance predictions
- Comprehensive player reports
- Top players analysis

## 📦 Installation

1. Install required packages:
```bash
pip install -r nba_requirements.txt
```

2. Create project directory:
```bash
mkdir nba_project
cd nba_project
```

3. Run desired script:
```bash
python nba_scraper.py
# or
python nba_csv_downloader.py
# or
python nba_player_analyzer.py
```

## 🚀 Quick Start Examples

### Example 1: Download Season Statistics
```python
from nba_csv_downloader import NBACSVDownloader

downloader = NBACSVDownloader(delay=2)

# Get 2023-24 season stats
season_stats = downloader.get_season_stats(2024, 'per_game')
print(f"Downloaded stats for {len(season_stats)} players")
```

### Example 2: Analyze Player Performance
```python
from nba_player_analyzer import NBAPlayerAnalyzer

analyzer = NBAPlayerAnalyzer(delay=2)

# Analyze LeBron's scoring trends
trends = analyzer.analyze_player_trends('LeBron James', 'PTS', num_games=10)
print(f"Last 10 games average: {trends['average']:.1f} PPG")
```

### Example 3: Compare Players
```python
# Compare top players
comparison = analyzer.compare_players(
    ['LeBron James', 'Kevin Durant', 'Stephen Curry'],
    season=2024
)
print(comparison[['Player', 'PTS', 'AST', 'TRB']])
```

### Example 4: Get Team Statistics
```python
from nba_csv_downloader import NBACSVDownloader

downloader = NBACSVDownloader()

# Get Lakers statistics
lakers_stats = downloader.get_team_stats('LAL', 2024)
for stat_type, df in lakers_stats.items():
    print(f"{stat_type}: {len(df)} rows")
```

## 📊 Data Types Available

### Player Data
- **Career Statistics**: Per game, totals, per 36 minutes, advanced
- **Game Logs**: Game-by-game performance data
- **Shooting**: Shot charts and shooting percentages
- **Advanced Metrics**: PER, WS, BPM, VORP, etc.

### Team Data
- **Rosters**: Current and historical rosters
- **Team Statistics**: Offensive and defensive ratings
- **Standings**: Conference and division standings
- **Head-to-Head**: Team matchup history

### League Data
- **Season Leaders**: Statistical leaders by category
- **All-Star Data**: All-Star game rosters and stats
- **Draft Data**: Draft picks and combine measurements
- **Playoff Data**: Playoff statistics and series results

## 🎯 Use Cases

### For Data Scientists
- Build predictive models for player performance
- Analyze team chemistry and synergies
- Create advanced statistical metrics
- Historical trend analysis

### For Fantasy Basketball
- Player projections and rankings
- Matchup analysis
- Injury impact assessment
- Trade evaluation tools

### For Sports Analysts
- Player comparison reports
- Season recap analysis
- Career trajectory studies
- Team performance evaluation

### For Developers
- Build sports analytics applications
- Create visualization dashboards
- Develop betting models
- API data source for apps

## ⚙️ Configuration

### Rate Limiting
Always use appropriate delays between requests:
```python
scraper = NBAReferenceScraper(delay=3)  # 3 seconds between requests
```

### Data Storage
Data is saved in organized directories:
```
nba_data/
├── players/        # Individual player data
├── teams/          # Team statistics
├── seasons/        # Season-wide data
├── playoffs/       # Playoff statistics
├── comparisons/    # Player comparisons
└── reports/        # Analysis reports
```

### Caching
The analyzer includes caching to reduce redundant requests:
```python
analyzer = NBAPlayerAnalyzer(delay=2)
# Previously downloaded data is cached locally
```

## 📈 Advanced Features

### Custom Analysis
Create custom analysis functions:
```python
def analyze_clutch_performance(player_name, season):
    """Analyze player performance in clutch situations"""
    # Your analysis code here
    pass
```

### Bulk Downloads
Download entire seasons efficiently:
```python
# Download complete 2023-24 season
season_data = downloader.bulk_download_season(2024)
```

### Historical Data
Access historical seasons:
```python
# Get Michael Jordan's 1996 stats
historical_stats = downloader.get_season_stats(1996, 'per_game')
```

## 🔧 Troubleshooting

### Common Issues

1. **Rate Limit Errors**
   - Increase delay between requests
   - Implement exponential backoff

2. **Missing Data**
   - Some statistics may not be available for all seasons
   - Check if player name matches exactly

3. **Connection Errors**
   - Verify internet connection
   - Check if Basketball Reference is accessible

4. **Parsing Errors**
   - Website structure may have changed
   - Update selectors and parsing logic

## 📝 Best Practices

1. **Respect Rate Limits**: Use minimum 2-3 second delays
2. **Cache Data**: Store downloaded data to avoid redundant requests
3. **Error Handling**: Implement robust error handling
4. **Incremental Updates**: Download only new/updated data
5. **Attribution**: Always credit Basketball-Reference.com

## 🚫 What NOT to Do

- Don't make rapid consecutive requests
- Don't use for commercial purposes without permission
- Don't redistribute large datasets
- Don't ignore robots.txt restrictions
- Don't use for real-time applications

## 📚 Data Dictionary

### Common Statistics Abbreviations
- **PTS**: Points
- **AST**: Assists
- **TRB**: Total Rebounds
- **STL**: Steals
- **BLK**: Blocks
- **FG%**: Field Goal Percentage
- **3P%**: Three-Point Percentage
- **FT%**: Free Throw Percentage
- **PER**: Player Efficiency Rating
- **WS**: Win Shares
- **BPM**: Box Plus/Minus
- **VORP**: Value Over Replacement Player

## 🔄 Updating Data

To keep data current:
```bash
# Run daily/weekly updates
python update_stats.py --season 2025 --type daily
```

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Submit a pull request

## ⚖️ License & Legal

This tool is for educational purposes. Basketball-Reference.com data is property of Sports Reference LLC. Users must comply with their Terms of Service and copyright policies.

## 🔗 Resources

- Basketball Reference: https://www.basketball-reference.com
- Documentation: https://www.sports-reference.com/termsofuse.html
- NBA Official Stats: https://www.nba.com/stats

## 📧 Support

For issues or questions about:
- The scraping tools: Create an issue in the repository
- Basketball Reference data: Contact Sports Reference LLC
- NBA data rights: Contact the NBA

## 🎉 Acknowledgments

- Basketball-Reference.com for providing comprehensive NBA data
- Sports Reference LLC for maintaining historical statistics
- The open-source community for Python libraries

---

**Remember**: Always use these tools responsibly and in accordance with Basketball Reference's Terms of Service!