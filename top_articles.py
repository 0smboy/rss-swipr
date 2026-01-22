#!/usr/bin/env python3
"""Show top ML-ranked articles from the last N hours in a browser."""

import argparse
import sqlite3
import pickle
import sys
import tempfile
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

# Add ml directory to path for unpickling
sys.path.insert(0, str(Path(__file__).parent / 'ml'))

def load_model():
    """Load the hybrid RF model."""
    model_path = Path(__file__).parent / 'ml' / 'models' / 'hybrid_rf.pkl'
    with open(model_path, 'rb') as f:
        return pickle.load(f)

def get_recent_articles(hours: int) -> pd.DataFrame:
    """Get articles from the last N hours."""
    db_path = Path(__file__).parent / 'rss_reader.db'
    conn = sqlite3.connect(str(db_path))

    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.isoformat()

    query = """
    SELECT e.id as entry_id, e.title, e.link, e.description, e.content,
           e.author, e.published_at, e.categories, e.has_media, e.word_count,
           f.name as feed_name
    FROM entries e
    JOIN feeds f ON e.feed_id = f.id
    WHERE e.published_at >= ?
    ORDER BY e.published_at DESC
    """

    df = pd.read_sql_query(query, conn, params=[cutoff_str])
    conn.close()
    return df

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add required features for the model."""
    from urllib.parse import urlparse

    # Domain
    def extract_domain(url):
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return 'unknown'

    df['domain'] = df['link'].apply(extract_domain)

    # Temporal features
    df['published_at_dt'] = pd.to_datetime(df['published_at'], errors='coerce')
    now = datetime.now()
    df['voted_at_dt'] = now  # Use current time as "vote" time

    df['pub_day_of_week'] = df['published_at_dt'].dt.dayofweek.fillna(-1).astype(int)
    df['pub_hour'] = df['published_at_dt'].dt.hour.fillna(-1).astype(int)
    df['pub_is_weekend'] = (df['pub_day_of_week'] >= 5).astype(int)

    df['vote_day_of_week'] = now.weekday()
    df['vote_hour'] = now.hour
    df['vote_is_weekend'] = 1 if now.weekday() >= 5 else 0

    df['days_since_published'] = (now - df['published_at_dt']).dt.total_seconds() / (24 * 3600)
    df['days_since_published'] = df['days_since_published'].fillna(0)

    # Text features
    df['title_char_count'] = df['title'].fillna('').str.len()
    df['title_word_count'] = df['title'].fillna('').str.split().str.len()
    df['description_char_count'] = df['description'].fillna('').str.len()
    df['description_word_count'] = df['description'].fillna('').str.split().str.len()
    df['content_char_count'] = df['content'].fillna('').str.len()
    df['reading_time_minutes'] = df['word_count'].fillna(0) / 200

    # Behavioral (zeros for new articles)
    df['open_count'] = 0
    df['total_time'] = 0

    return df

def score_articles(df: pd.DataFrame, model_data: dict) -> np.ndarray:
    """Score articles using the model."""
    feature_pipeline = model_data['feature_pipeline']
    scaler = model_data['scaler']
    model = model_data['model']

    # Extract engineered features
    engineered = feature_pipeline.transform(df)

    # Create zero embeddings (768 dims)
    embeddings = np.zeros((len(df), 768))

    # Combine
    X = np.hstack([embeddings, engineered])
    X_scaled = scaler.transform(X)

    # Get probability of "like" (class 2)
    proba = model.predict_proba(X_scaled)
    return proba[:, 2]  # Like probability

def generate_html(df: pd.DataFrame, hours: int) -> str:
    """Generate HTML page for top articles."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Top Articles - Last {hours}h</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #007AFF;
            padding-bottom: 10px;
        }}
        .article {{
            background: white;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .article:hover {{
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }}
        .rank {{
            display: inline-block;
            width: 28px;
            height: 28px;
            background: #007AFF;
            color: white;
            border-radius: 50%;
            text-align: center;
            line-height: 28px;
            font-weight: bold;
            font-size: 14px;
            margin-right: 12px;
        }}
        .title {{
            font-size: 18px;
            font-weight: 600;
            color: #1a1a1a;
            text-decoration: none;
        }}
        .title:hover {{ color: #007AFF; }}
        .meta {{
            color: #666;
            font-size: 13px;
            margin-top: 8px;
        }}
        .score {{
            display: inline-block;
            background: #e8f5e9;
            color: #2e7d32;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 500;
            font-size: 12px;
        }}
        .feed {{ color: #007AFF; }}
        .description {{
            color: #444;
            font-size: 14px;
            margin-top: 8px;
            line-height: 1.5;
        }}
        .generated {{
            text-align: center;
            color: #999;
            font-size: 12px;
            margin-top: 30px;
        }}
    </style>
</head>
<body>
    <h1>Top 25 Articles - Last {hours} Hours</h1>
"""

    for i, row in df.iterrows():
        rank = i + 1
        score_pct = row['score'] * 100
        desc = row['description'][:200] + '...' if len(str(row['description'])) > 200 else row['description']

        html += f"""
    <div class="article">
        <span class="rank">{rank}</span>
        <a href="{row['link']}" target="_blank" class="title">{row['title']}</a>
        <div class="meta">
            <span class="score">{score_pct:.0f}% match</span>
            <span class="feed">{row['feed_name']}</span>
            &middot; {row['published_at'][:16]}
        </div>
        <div class="description">{desc}</div>
    </div>
"""

    html += f"""
    <p class="generated">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body>
</html>
"""
    return html

def main():
    parser = argparse.ArgumentParser(description='Show top ML-ranked articles')
    parser.add_argument('hours', type=int, help='Number of hours to look back (e.g., 24, 48)')
    parser.add_argument('-n', '--num', type=int, default=25, help='Number of articles to show (default: 25)')
    args = parser.parse_args()

    print(f"Loading articles from last {args.hours} hours...")
    df = get_recent_articles(args.hours)

    if len(df) == 0:
        print("No articles found in that time period.")
        return

    print(f"Found {len(df)} articles, scoring...")
    df = add_features(df)

    model_data = load_model()
    df['score'] = score_articles(df, model_data)

    # Sort by score and take top N
    df = df.nlargest(args.num, 'score').reset_index(drop=True)

    print(f"Top {len(df)} articles:")
    for i, row in df.iterrows():
        print(f"  {i+1:2}. [{row['score']*100:4.0f}%] {row['title'][:60]}")

    # Generate HTML and open in browser
    html = generate_html(df, args.hours)

    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False) as f:
        f.write(html)
        temp_path = f.name

    print(f"\nOpening in browser...")
    webbrowser.open(f'file://{temp_path}')

if __name__ == '__main__':
    main()
