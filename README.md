# RSS Swipr

A swipe-based RSS reader that learns your preferences. Swipe through articles to train a personalized ML model that recommends content you'll enjoy.

## Quick Start

```bash
# Clone and setup
git clone https://github.com/philippdubach/rss-swipr.git
cd rss-swipr
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

## Usage

### 1. Add RSS Feeds

1. Click **Settings** (gear icon)
2. Go to **Feeds** tab
3. Paste CSV or upload a file:
   ```csv
   name,url
   Hacker News,https://news.ycombinator.com/rss
   TechCrunch,https://techcrunch.com/feed/
   ```
4. Click **Refresh Feeds** to fetch articles

### 2. Swipe Articles

- **Swipe right** = Like
- **Swipe up** = Neutral
- **Swipe left** = Dislike

The app tracks your votes, link clicks, and reading time to build training data.

### 3. Train Your Model

Once you have enough votes (50+ recommended):

1. **Export**: Settings → Export → Download Training Data (CSV)
2. **Train**: Open the [Google Colab notebook](https://colab.research.google.com/drive/1XjnAuwF3naPElKH9yZ3UEdslzN7qAUrQ?usp=sharing), upload your CSV, run all cells
3. **Upload**: Settings → Models → Upload the generated `.pkl` file
4. **Activate**: Click "Activate" to use your model for recommendations

### 4. Backup & Restore

To use your training data on a fresh install:

1. Keep your `training_data.csv` from the export step
2. On new install: import feeds, refresh to fetch articles
3. Settings → Export → Import Training Data (upload your CSV)

This restores your voting history by matching articles via URL.

## How It Works

- **Thompson Sampling**: 80% exploit (best predictions), 20% explore (diversity)
- **Hybrid Features**: Combines text analysis with behavioral signals
- **No cloud dependency**: All data stays local in SQLite databases

## Project Structure

```
rss-swipr/
├── app.py              # Flask server
├── src/                # Python modules (feeds, tracking, models)
├── ml/                 # ML pipeline and trained models
├── static/             # Frontend (JS, CSS)
├── templates/          # HTML
└── notebooks/          # Model training notebook
```

## Requirements

- Python 3.8+
- Dependencies: Flask, pandas, scikit-learn, xgboost, feedparser

## License

MIT
