# RSS Swipr - ML-Powered RSS Reader

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Flask](https://img.shields.io/badge/Flask-3.1.0-green.svg)](https://flask.palletsprojects.com/)

An intelligent RSS feed reader with a Tinder-style swipe interface that learns your preferences and recommends articles you'll love. Powered by a hybrid ML model achieving **75.4% ROC-AUC** on personalized recommendations.

## Features

- **ML-Powered Recommendations**: Hybrid Random Forest model combining transformer embeddings (MPNet) with 1,407 engineered features
- **Swipe Interface**: Swipe left (dislike), up (neutral), right (like) to train the model
- **Web-Based Feed Management**: Import feeds via CSV upload or web UI, no manual file editing
- **Model Upload System**: Train custom models on Google Colab and upload via web interface
- **Engagement Tracking**: Automatically tracks article opens, reading time, and voting patterns
- **Smart Caching**: HTTP ETag/Last-Modified caching prevents redundant fetches
- **Duplicate Detection**: GUID-based deduplication across feeds

## Architecture

```
rss-swipr/
├── app.py                 # Flask API server (main entry point)
├── src/                   # Python source modules
│   ├── __init__.py        # Package exports
│   ├── tracking_db.py     # User engagement tracking (votes, opens, time)
│   ├── feed_manager.py    # RSS feed CRUD operations
│   ├── model_manager.py   # ML model upload & switching
│   ├── rss_fetcher.py     # RSS feed fetching & parsing
│   └── og_fetcher.py      # Open Graph metadata extraction
├── ml/                    # Machine learning pipeline
│   ├── __init__.py        # Package exports
│   ├── feature_engineering.py  # 1,407 feature extraction pipeline
│   └── models/            # Trained model artifacts (.pkl files)
│       └── uploads/       # User-uploaded custom models
├── templates/             # HTML templates
│   └── index.html         # Main swipe interface
├── static/                # Frontend assets
│   ├── app.js             # Swipe card logic
│   ├── settings.js        # Feed/model management UI
│   └── style.css          # Styling
├── notebooks/             # Model training notebooks
│   └── retrain_model.ipynb
├── rss_reader.db          # SQLite database (feeds & articles)
├── tracking.db            # SQLite database (user engagement)
└── start.sh               # Quick start script
```

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/philippdubach/rss-swipr.git
cd rss-swipr

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt
```

### Run the Web App

```bash
# Option 1: Quick start script
./start.sh

# Option 2: Direct Python
python app.py
```

Open your browser to: **http://127.0.0.1:5000**

### First-Time Setup

1. Click the **Settings** button (⚙️ top-right)
2. Navigate to the **Feeds** tab
3. Import RSS feeds by pasting CSV or uploading a file:
   ```csv
   name,url
   TechCrunch,https://techcrunch.com/feed/
   Hacker News,https://news.ycombinator.com/rss
   Ars Technica,https://feeds.arstechnica.com/arstechnica/index
   ```
4. Click **Refresh Feeds** to fetch articles
5. Start swiping on the main page to train your personalized model!

## Machine Learning Pipeline

### Model Performance

| Model | ROC-AUC | Description |
|-------|---------|-------------|
| TF-IDF + Logistic Regression | 0.664 | Baseline |
| **Hybrid RF (Production)** | **0.754** | MPNet embeddings + engineered features |
| XGBoost Ensemble | 0.694 | Overfit on small dataset |

### Training Your Own Model

1. **Collect Training Data**:
   - Swipe on articles (left = dislike, up = neutral, right = like)
   - Go to Settings → Export tab → Download training data CSV

2. **Train on Google Colab** (requires GPU for MPNet embeddings):
   - Upload: `training_data_v2.csv` and `ml/feature_engineering.py`
   - Run: `notebooks/retrain_model.ipynb`
   - Download: `hybrid_rf.pkl`

3. **Upload Custom Model**:
   - Settings → Models tab → Upload your `.pkl` file
   - Activate the new model to use it for recommendations

### Feature Engineering

The hybrid model uses **1,407 features**:
- **MPNet Embeddings** (768 dims): Semantic understanding via transformer model
- **Text Features** (500+): TF-IDF, n-grams, readability metrics
- **Behavioral Features**: Feed preferences, engagement patterns
- **Interaction Features**: Cross-feature combinations

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/posts/next` | GET | Get next ML-recommended article |
| `/api/posts/batch` | GET | Get batch of 3-5 preloaded articles |
| `/api/vote` | POST | Record swipe vote (like/neutral/dislike) |
| `/api/open` | POST | Track article link click |
| `/api/time` | POST | Track time spent on article |
| `/api/feeds` | GET/POST | List or import RSS feeds |
| `/api/feeds/refresh` | GET | Fetch new articles (SSE stream) |
| `/api/models` | GET/POST | List or upload ML models |
| `/api/export/training-data` | GET | Download training data CSV |

## Database Schema

### rss_reader.db
- **feeds**: RSS feed URLs, metadata, HTTP cache headers
- **entries**: Articles with content, author, published date, GUID

### tracking.db
- **user_votes**: Swipe votes (like/neutral/dislike) per article
- **link_opens**: Article click tracking
- **time_spent**: Reading time per article
- **models**: Uploaded model registry

## Troubleshooting

### Model Upload Error: "No module named 'feature_engineering'"

**Fixed in v1.1** - The pickle file requires the `feature_engineering` module to deserialize. The app now automatically adds the `ml/` directory to Python's import path.

If you still see this error:
- Ensure `ml/feature_engineering.py` exists
- Restart the Flask server (`python app.py`)

### CSV Upload Error: "Unexpected token '<'"

**Fixed in v1.1** - The server now returns proper JSON error messages instead of HTML error pages.

If you see this error:
- Check CSV format is correct: `name,url` (two columns)
- Don't paste HTML content - only CSV text
- Ensure file is UTF-8 encoded

##  Experiment Results

The project includes comprehensive ML experiments in `notebooks/`:

1. **Data Exploration**: Understanding the dataset and class distribution
2. **Baseline Models**: TF-IDF, bag-of-words, traditional ML
3. **Transformer Embeddings**: MPNet, sentence-transformers
4. **Data Augmentation**: Synthetic data generation (inconclusive)
5. **Ensemble Optimization**: Optuna hyperparameter tuning

Key finding: With limited training data (~500 samples), simpler models with good features outperform complex architectures.

##  Development

### Running Tests

```bash
python -m pytest tests/
```

### Code Style

```bash
# Format code
black src/ ml/

# Lint
flake8 src/ ml/
```

##  License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

##  Acknowledgments

- [feedparser](https://feedparser.readthedocs.io/) - Universal feed parser
- [sentence-transformers](https://www.sbert.net/) - State-of-the-art embeddings
- [scikit-learn](https://scikit-learn.org/) - Machine learning library
- [Optuna](https://optuna.org/) - Hyperparameter optimization

---

**Keywords**: RSS reader, machine learning, recommendation system, NLP, Python, transformer embeddings, MPNet, scikit-learn, feed aggregator, content recommendation
