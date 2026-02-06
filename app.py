"""
Flask API server for RSS Swipr app.
Serves posts and tracks user engagement.

Uses Hybrid RF model (0.7443 ROC-AUC) for ML-powered recommendations.
Falls back to random selection if model unavailable.
"""
from flask import Flask, jsonify, request, render_template, send_from_directory, Response
from src.tracking_db import TrackingDatabase
from src.model_manager import ModelManager
from src.feed_manager import FeedManager
from src.og_fetcher import fetch_og_sync
import re
import sys
import io
import json
import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from html import unescape
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)
db = TrackingDatabase()
model_manager = ModelManager(db)
feed_manager = FeedManager()

# ML Model Loading
ML_DIR = Path(__file__).parent / 'ml'

# Add ml directory to path for feature_engineering module
sys.path.insert(0, str(ML_DIR))

# Load model via model manager
ML_MODEL = model_manager.get_current_model()
USE_ML = ML_MODEL is not None

if USE_ML:
    roc_auc = ML_MODEL.get('results', {}).get('mean_roc_auc', 'N/A')
    print(f"✓ Loaded ML model")
    print(f"  ROC-AUC: {roc_auc}")
else:
    print("⚠ No model available, falling back to random selection")


@app.route('/')
def index():
    """Serve the main app page."""
    return render_template('index.html')


def extract_hybrid_features(article):
    """
    Extract features for Hybrid RF model.
    Uses the trained feature pipeline from the model.
    """
    # Build a dataframe that matches training data format
    title = article.get('title', '') or ''
    description = article.get('description', '') or ''
    content = article.get('content', '') or ''
    
    # Parse published date
    published_at = article.get('published_at')
    if published_at:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            pub_day_of_week = dt.weekday()
            pub_hour = dt.hour
            pub_is_weekend = int(pub_day_of_week >= 5)
        except:
            pub_day_of_week, pub_hour, pub_is_weekend = 0, 12, 0
    else:
        pub_day_of_week, pub_hour, pub_is_weekend = 0, 12, 0
    
    # Build feature dict matching training data columns
    data = {
        'title': title,
        'description': description,
        'content': content,
        'feed_name': article.get('feed_name', 'unknown'),
        'author': article.get('author', ''),
        'word_count': article.get('word_count', 0) or len(description.split()),
        'has_media': int(article.get('has_media', 0) or 0),
        'title_char_count': len(title),
        'title_word_count': len(title.split()),
        'description_char_count': len(description),
        'description_word_count': len(description.split()),
        'reading_time_minutes': (article.get('word_count', 0) or 0) / 200,
        'vote_hour': 12,  # Use default for new articles
        'vote_day_of_week': 3,
        'vote_is_weekend': 0,
        'days_since_published': 0,
        'open_count': 0,
        'total_time': 0
    }
    
    return pd.DataFrame([data])


def score_post_hybrid(article, model_data):
    """Score a post using the Hybrid RF model"""
    try:
        # Extract features
        df = extract_hybrid_features(article)
        
        # Get model components
        model = model_data['model']
        feature_pipeline = model_data['feature_pipeline']
        scaler = model_data['scaler']
        
        # Transform features (without embeddings - use zeros as placeholder)
        engineered = feature_pipeline.transform(df)
        engineered_scaled = scaler.transform(engineered)
        
        # For production without embeddings, we use a zero vector
        # This is a simplification - full accuracy requires sentence-transformers
        embedding_dim = 768  # MPNet dimension
        dummy_embedding = np.zeros((1, embedding_dim))
        
        X = np.hstack([dummy_embedding, engineered_scaled])
        
        # Predict
        probs = model.predict_proba(X)[0]
        
        return {
            'dislike_prob': float(probs[0]),
            'neutral_prob': float(probs[1]),
            'like_prob': float(probs[2])
        }
    except Exception as e:
        print(f"Error in hybrid scoring: {e}")
        return None


def score_all_posts(unvoted_posts):
    """Score a list of posts using Hybrid RF model."""
    scores = []

    for post in unvoted_posts:
        try:
            score_result = score_post_hybrid(post, ML_MODEL)
            if score_result:
                like_prob = score_result['like_prob']
                neutral_prob = score_result['neutral_prob']
            else:
                continue

            # Calculate utility score
            utility = like_prob * 2 + neutral_prob * 1

            # Boost score for newer posts (recency bonus)
            recency_index = len(scores)
            recency_boost = 1 + (0.2 * max(0, (50 - recency_index) / 50))
            utility = utility * recency_boost

            scores.append({
                'post': post,
                'utility': utility,
                'like_prob': like_prob,
                'recency_index': recency_index
            })
        except Exception as e:
            print(f"Error scoring post {post.get('id')}: {e}")
            continue

    return scores


def select_ml_post(exclude_ids=None):
    """Select post using ML model with Thompson Sampling, prioritizing recent posts.

    Args:
        exclude_ids: List of entry IDs to exclude (e.g., posts already in queue)
    """
    # Get top 100 recent unvoted posts for better selection
    unvoted_posts = db.get_all_unvoted_posts(limit=100, exclude_ids=exclude_ids)
    
    if not unvoted_posts:
        return None
    
    scores = score_all_posts(unvoted_posts)
    
    if not scores:
        return None
    
    # Thompson Sampling: 80% exploit best, 20% explore
    if np.random.random() < 0.8:
        best = max(scores, key=lambda x: x['utility'])
        selected_post = best['post']
    else:
        utilities = np.array([s['utility'] for s in scores])
        utilities = utilities / utilities.sum()
        idx = np.random.choice(len(scores), p=utilities)
        selected_post = scores[idx]['post']
    
    return selected_post


def select_ml_posts_batch(count=3, exclude_ids=None):
    """Select multiple posts using ML model with Thompson Sampling and feed diversity.

    Args:
        count: Number of posts to select (1-5)
        exclude_ids: List of entry IDs to exclude (already in user's queue)

    Returns:
        List of selected posts with diversity via Thompson Sampling
    """
    exclude_ids = set(exclude_ids or [])

    # Get top 100 recent unvoted posts (already diversified by feed)
    unvoted_posts = db.get_all_unvoted_posts(limit=100, exclude_ids=list(exclude_ids))

    if not unvoted_posts:
        return []

    scores = score_all_posts(unvoted_posts)

    if not scores:
        return []

    selected = []
    selected_feeds = set()  # Track feeds we've already selected from
    remaining_scores = scores.copy()

    for _ in range(min(count, len(remaining_scores))):
        if not remaining_scores:
            break

        # Apply feed diversity penalty - reduce utility for feeds already in batch
        adjusted_scores = []
        for s in remaining_scores:
            feed = s['post'].get('feed_name', '')
            penalty = 0.3 if feed in selected_feeds else 1.0  # 70% penalty for repeat feeds
            adjusted_scores.append({
                **s,
                'adjusted_utility': s['utility'] * penalty
            })

        # Thompson Sampling: 80% exploit best, 20% explore
        if np.random.random() < 0.8:
            best = max(adjusted_scores, key=lambda x: x['adjusted_utility'])
            selected_idx = adjusted_scores.index(best)
        else:
            utilities = np.array([s['adjusted_utility'] for s in adjusted_scores])
            utilities = utilities / utilities.sum()
            selected_idx = np.random.choice(len(adjusted_scores), p=utilities)

        chosen_post = remaining_scores[selected_idx]['post']
        selected.append(chosen_post)
        selected_feeds.add(chosen_post.get('feed_name', ''))
        remaining_scores.pop(selected_idx)
    
    return selected


def truncate_text(text, max_length=200):
    """Truncate text at word boundary with ellipsis."""
    if not text or len(text) <= max_length:
        return text
    # Find last space before max_length
    truncated = text[:max_length]
    last_space = truncated.rfind(' ')
    if last_space > max_length * 0.6:  # Only use word boundary if reasonable
        truncated = truncated[:last_space]
    return truncated.rstrip('.,;:!?') + '...'


def format_post_response(post):
    """Format a post for API response. Shared by /api/posts/next and /api/posts/batch."""
    # Helper function to strip HTML tags
    def strip_html(text):
        if not text:
            return ''
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Unescape HTML entities
        text = unescape(text)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    # Prioritize summary/description, only use full content if neither exists
    # Apply consistent truncation to all sources
    description_text = ''
    if post.get('summary'):
        description_text = truncate_text(strip_html(post['summary']))
    elif post.get('description'):
        description_text = truncate_text(strip_html(post['description']))
    elif post.get('content'):
        description_text = truncate_text(strip_html(post['content']))

    # Extract image URL: try enclosure first, then HTML content
    image_url = None
    enclosure_url = post.get('enclosure_url')
    enclosure_type = post.get('enclosure_type', '') or ''
    if enclosure_url and enclosure_type.startswith('image/'):
        image_url = enclosure_url
    else:
        # Try to extract first image from HTML content
        content = post.get('content') or post.get('description') or ''
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
        if img_match:
            image_url = img_match.group(1)

    return {
        'id': post['id'],
        'title': post.get('title') or 'Untitled',
        'description': description_text or 'No description available.',
        'link': post.get('link') or '',
        'permalink': post.get('permalink') or post.get('link') or '',
        'author': post.get('author') or '',
        'feed_name': post.get('feed_name') or 'Unknown',
        'published_at': post.get('published_at'),
        'categories': post.get('categories') or '',
        'has_media': post.get('has_media') or False,
        'image_url': image_url
    }


@app.route('/api/posts/batch', methods=['GET'])
def get_posts_batch():
    """Get multiple recommended posts in a single request for preloading.
    
    Query params:
        count: Number of posts to fetch (1-5, default 3)
        exclude: Comma-separated list of entry IDs to exclude (already in queue)
    """
    count = min(max(int(request.args.get('count', 3)), 1), 5)  # Clamp to 1-5
    exclude_str = request.args.get('exclude', '')
    exclude_ids = [int(x) for x in exclude_str.split(',') if x.strip().isdigit()]
    
    posts = []
    
    # Try ML selection first
    if USE_ML:
        try:
            selected = select_ml_posts_batch(count=count, exclude_ids=exclude_ids)
            for post in selected:
                post['ml_recommended'] = True
                posts.append(format_post_response(post))
        except Exception as e:
            print(f"ML batch selection failed: {e}")
    
    # If we don't have enough posts, fill with random
    if len(posts) < count:
        remaining = count - len(posts)
        all_exclude = exclude_ids + [p['id'] for p in posts]
        random_posts = db.get_random_unvoted_posts(limit=remaining, exclude_ids=all_exclude)
        for post in random_posts:
            post['ml_recommended'] = False
            posts.append(format_post_response(post))
    
    if not posts:
        return jsonify({'posts': [], 'message': 'No more posts available'}), 200
    
    return jsonify({'posts': posts, 'count': len(posts)})


@app.route('/api/posts/next', methods=['GET'])
def get_next_post():
    """Get next recommended post (ML-powered or random).

    Query params:
        exclude: Comma-separated list of entry IDs to exclude (already in queue)
    """
    # Parse exclude IDs from query param
    exclude_str = request.args.get('exclude', '')
    exclude_ids = [int(x) for x in exclude_str.split(',') if x.strip().isdigit()]

    # Try ML selection first
    if USE_ML:
        try:
            post = select_ml_post(exclude_ids=exclude_ids)
            if post:
                post['ml_recommended'] = True
        except Exception as e:
            print(f"ML selection failed: {e}, falling back to random")
            post = None
    else:
        post = None

    # Fallback to random
    if not post:
        post = db.get_random_unvoted_post(exclude_ids=exclude_ids)
        if post:
            post['ml_recommended'] = False

    if not post:
        return jsonify({'error': 'No more posts available'}), 404

    return jsonify(format_post_response(post))


@app.route('/api/vote', methods=['POST'])
def record_vote():
    """Record a user vote (like/neutral/dislike)."""
    data = request.json
    entry_id = data.get('entry_id')
    vote = data.get('vote')
    
    if not entry_id or not vote:
        return jsonify({'error': 'Missing entry_id or vote'}), 400
    
    if vote not in ['like', 'neutral', 'dislike']:
        return jsonify({'error': 'Invalid vote type'}), 400
    
    success = db.record_vote(entry_id, vote)
    
    if success:
        return jsonify({'success': True, 'message': 'Vote recorded'})
    else:
        return jsonify({'error': 'Failed to record vote'}), 500


@app.route('/api/open', methods=['POST'])
def record_open():
    """Record when a user opens an article link."""
    data = request.json
    entry_id = data.get('entry_id')
    
    if not entry_id:
        return jsonify({'error': 'Missing entry_id'}), 400
    
    db.record_link_open(entry_id)
    return jsonify({'success': True, 'message': 'Link open recorded'})


@app.route('/api/time', methods=['POST'])
def record_time():
    """Record time spent on a post."""
    data = request.json
    entry_id = data.get('entry_id')
    seconds = data.get('seconds')
    
    if not entry_id or seconds is None:
        return jsonify({'error': 'Missing entry_id or seconds'}), 400
    
    db.record_time_spent(entry_id, int(seconds))
    return jsonify({'success': True, 'message': 'Time recorded'})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get overall statistics."""
    stats = db.get_stats()
    stats['ml_model'] = {
        'enabled': USE_ML,
        'type': 'hybrid_rf' if USE_ML else None
    }
    return jsonify(stats)


@app.route('/api/entry/<int:entry_id>', methods=['GET'])
def get_entry_details(entry_id):
    """Get detailed tracking data for an entry."""
    details = db.get_entry_details(entry_id)

    if details:
        return jsonify(details)
    else:
        return jsonify({'error': 'Entry not found'}), 404


# =====================
# Feed Management API
# =====================

@app.route('/api/feeds', methods=['GET'])
def get_feeds():
    """Get all feeds with stats."""
    try:
        feeds = feed_manager.get_feeds()
        stats = feed_manager.get_feed_stats()
        return jsonify({'feeds': feeds, 'stats': stats})
    except Exception as e:
        print(f"[ERROR] Failed to get feeds: {str(e)}")
        return jsonify({'error': f'Failed to load feeds: {str(e)}'}), 500


@app.route('/api/feeds', methods=['POST'])
def import_feeds():
    """Import feeds from OPML file upload."""
    try:
        # Handle file upload
        if 'file' in request.files:
            file = request.files['file']
            if file.filename:
                try:
                    opml_content = file.read().decode('utf-8')
                except UnicodeDecodeError:
                    return jsonify({'success': False, 'error': 'File must be UTF-8 encoded text'}), 400
                
                # Validate it's XML/OPML
                if not opml_content.strip().startswith('<?xml') and not '<opml' in opml_content.lower():
                    return jsonify({
                        'success': False, 
                        'error': 'Invalid OPML format. Expected XML document with <opml> root element.'
                    }), 400
                
                result = feed_manager.import_opml(opml_content)
                return jsonify(result)

        # Handle JSON body with opml_content
        data = request.json or {}
        opml_content = data.get('opml_content', '')

        if not opml_content:
            return jsonify({'success': False, 'error': 'No OPML content provided'}), 400

        # Validate it's XML/OPML
        if not opml_content.strip().startswith('<?xml') and not '<opml' in opml_content.lower():
            return jsonify({
                'success': False, 
                'error': 'Invalid OPML format. Expected XML document with <opml> root element.'
            }), 400

        result = feed_manager.import_opml(opml_content)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Import failed: {str(e)}'}), 500


@app.route('/api/feeds/<int:feed_id>', methods=['DELETE'])
def delete_feed(feed_id):
    """Delete a feed and its entries."""
    success, message = feed_manager.delete_feed(feed_id)
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'error': message}), 400


@app.route('/api/feeds/<int:feed_id>/toggle', methods=['POST'])
def toggle_feed(feed_id):
    """Toggle feed active status."""
    success, new_status = feed_manager.toggle_feed(feed_id)
    if success:
        return jsonify({'success': True, 'active': new_status})
    else:
        return jsonify({'error': 'Failed to toggle feed'}), 400


@app.route('/api/feeds/refresh', methods=['GET'])
def refresh_feeds():
    """Fetch new articles from all active feeds with SSE progress updates."""
    import time
    from src.rss_fetcher import RSSFetcher

    def generate():
        try:
            fetcher = RSSFetcher(db_path="rss_reader.db")

            # Get all active feeds
            feeds = fetcher.get_all_feeds(active_only=True)
            total = len(feeds)
            results = []

            # Send initial progress
            yield f"data: {json.dumps({'type': 'progress', 'current': 0, 'total': total, 'message': f'Starting refresh of {total} feeds...'})}\n\n"

            for i, feed in enumerate(feeds):
                # Send progress update
                feed_name = feed['name']
                msg = f"Fetching {i+1}/{total}: {feed_name[:30]}..."
                progress = {'type': 'progress', 'current': i, 'total': total, 'feed_name': feed_name, 'message': msg}
                yield f"data: {json.dumps(progress)}\n\n"

                # Fetch this feed
                stats = fetcher.fetch_feed(feed['id'], feed['url'], feed_name)
                results.append(stats)

                # Small delay between feeds
                if i < total - 1:
                    time.sleep(0.5)

            # Send final result
            total_new = sum(r['entries_new'] for r in results)
            total_errors = sum(1 for r in results if r['error'])
            successful = sum(1 for r in results if r['success'])

            yield f"data: {json.dumps({'type': 'complete', 'success': True, 'feeds_fetched': len(results), 'feeds_successful': successful, 'feeds_failed': total_errors, 'entries_new': total_new})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


# =====================
# Model Management API
# =====================

@app.route('/api/models', methods=['GET'])
def get_models():
    """Get all registered models."""
    status = model_manager.get_model_status()
    return jsonify(status)


@app.route('/api/models', methods=['POST'])
def upload_model():
    """Upload a new model file."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.endswith('.pkl'):
            return jsonify({'error': 'File must be a .pkl file'}), 400

        name = request.form.get('name', file.filename.replace('.pkl', ''))
        pkl_data = file.read()

        success, result = model_manager.save_uploaded_model(pkl_data, name)

        if success:
            return jsonify({'success': True, **result})
        else:
            return jsonify({'error': result.get('error', 'Upload failed')}), 400
    except Exception as e:
        print(f"[ERROR] Model upload failed: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500


@app.route('/api/models/<int:model_id>/activate', methods=['POST'])
def activate_model(model_id):
    """Activate a model for recommendations."""
    global ML_MODEL, USE_ML

    success = model_manager.activate_model(model_id)
    if success:
        ML_MODEL = model_manager.get_current_model()
        USE_ML = ML_MODEL is not None
        return jsonify({'success': True, 'message': 'Model activated'})
    else:
        return jsonify({'error': 'Failed to activate model'}), 400


@app.route('/api/models/<int:model_id>', methods=['DELETE'])
def delete_model(model_id):
    """Delete a model."""
    success, message = model_manager.delete_model(model_id)
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'error': message}), 400


# =====================
# Training Data Export
# =====================

@app.route('/api/export/training-data', methods=['GET'])
def export_training_data():
    """Export all voted entries as CSV for model training."""
    rss_db_path = Path(__file__).parent / 'rss_reader.db'

    import sqlite3
    rss_conn = sqlite3.connect(str(rss_db_path))
    rss_conn.row_factory = sqlite3.Row

    # Query joining entries with votes and engagement data
    # Columns match what the training notebook expects
    query = """
        SELECT
            e.id as entry_id,
            e.title,
            e.link,
            e.description,
            e.content,
            e.author,
            f.name as feed_name,
            e.published_at,
            e.word_count,
            e.has_media,
            e.categories
        FROM entries e
        JOIN feeds f ON e.feed_id = f.id
    """
    entries_df = pd.read_sql_query(query, rss_conn)
    rss_conn.close()

    # Get votes
    tracking_conn = sqlite3.connect(db.tracking_db_path)
    tracking_conn.row_factory = sqlite3.Row

    votes_df = pd.read_sql_query("SELECT entry_id, vote, voted_at FROM user_votes", tracking_conn)
    opens_df = pd.read_sql_query(
        "SELECT entry_id, COUNT(*) as open_count FROM link_opens GROUP BY entry_id",
        tracking_conn
    )
    time_df = pd.read_sql_query(
        "SELECT entry_id, SUM(seconds) as total_time FROM time_spent GROUP BY entry_id",
        tracking_conn
    )
    tracking_conn.close()

    # Merge
    df = entries_df.merge(votes_df, on='entry_id', how='inner')
    df = df.merge(opens_df, on='entry_id', how='left')
    df = df.merge(time_df, on='entry_id', how='left')

    df['open_count'] = df['open_count'].fillna(0).astype(int)
    df['total_time'] = df['total_time'].fillna(0).astype(int)

    # Generate CSV
    output = io.StringIO()
    df.to_csv(output, index=False)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=training_data.csv'}
    )


@app.route('/api/export/training-data/preview', methods=['GET'])
def preview_training_data():
    """Preview first 10 rows of training data."""
    rss_db_path = Path(__file__).parent / 'rss_reader.db'

    import sqlite3
    rss_conn = sqlite3.connect(str(rss_db_path))
    rss_conn.row_factory = sqlite3.Row

    query = """
        SELECT
            e.id as entry_id,
            e.title,
            f.name as feed_name,
            e.word_count
        FROM entries e
        JOIN feeds f ON e.feed_id = f.id
        LIMIT 1
    """
    rss_conn.close()

    # Get vote stats
    tracking_conn = sqlite3.connect(db.tracking_db_path)
    cursor = tracking_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM user_votes")
    total_votes = cursor.fetchone()[0]

    cursor.execute("""
        SELECT vote, COUNT(*) as count
        FROM user_votes GROUP BY vote
    """)
    vote_breakdown = {row[0]: row[1] for row in cursor.fetchall()}
    tracking_conn.close()

    return jsonify({
        'total_samples': total_votes,
        'vote_breakdown': vote_breakdown,
        'columns': [
            'entry_id', 'title', 'link', 'description', 'content', 'author',
            'feed_name', 'published_at', 'word_count', 'has_media', 'categories',
            'vote', 'voted_at', 'open_count', 'total_time'
        ]
    })


@app.route('/api/import/training-data', methods=['POST'])
def import_training_data():
    """Import training data from a CSV file.

    Matches entries by link URL to restore votes, opens, and time spent.
    Requires feeds to be imported and refreshed first.
    """
    try:
        # Handle file upload
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'File must be a .csv file'}), 400

        # Read CSV
        try:
            csv_content = file.read().decode('utf-8')
            df = pd.read_csv(io.StringIO(csv_content))
        except Exception as e:
            return jsonify({'error': f'Failed to parse CSV: {str(e)}'}), 400

        # Validate required columns
        required_cols = ['link', 'vote']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            return jsonify({'error': f'Missing required columns: {missing}'}), 400

        # Import the data
        stats = db.import_training_data(df)

        return jsonify({
            'success': True,
            'message': f"Imported {stats['votes_imported']} votes",
            **stats
        })

    except Exception as e:
        print(f"[ERROR] Training data import failed: {str(e)}")
        return jsonify({'error': f'Import failed: {str(e)}'}), 500


# =====================
# Open Graph API
# =====================

@app.route('/api/og/<int:entry_id>', methods=['GET'])
def get_og_metadata(entry_id):
    """Get Open Graph metadata for an entry.

    Query params:
        force: If 'true', bypass cache and refetch
    """
    force = request.args.get('force', '').lower() == 'true'

    # Get entry link from rss_reader.db
    rss_db_path = Path(__file__).parent / 'rss_reader.db'
    import sqlite3
    conn = sqlite3.connect(str(rss_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT link FROM entries WHERE id = ?", (entry_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'error': 'Entry not found'}), 404

    url = row[0]
    if not url:
        return jsonify({'error': 'Entry has no link'}), 400

    # Fetch OG data
    og_data = fetch_og_sync(db, entry_id, url, force=force)

    return jsonify(og_data)


if __name__ == '__main__':
    import os
    # host='0.0.0.0' allows access from other devices on the local network
    # To restrict to localhost only, change to host='127.0.0.1'
    # PORT can be customized via environment variable: PORT=5001 python app.py
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
