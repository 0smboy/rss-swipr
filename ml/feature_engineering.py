"""Feature Engineering Pipeline for RSS Reader ML

This module provides feature extraction classes for baseline models:
- TextFeatureExtractor: TF-IDF, n-grams, readability, sentiment
- BehavioralFeatureExtractor: User preference patterns
- InteractionFeatureExtractor: Feature interactions
- FeaturePipeline: Scikit-learn compatible pipeline combining all extractors
"""

import pandas as pd
import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from typing import Optional, List, Dict, Any
import warnings
warnings.filterwarnings('ignore')


class TextFeatureExtractor(BaseEstimator, TransformerMixin):
    """Extract text-based features from titles and descriptions"""

    def __init__(self,
                 max_tfidf_features: int = 500,
                 ngram_range: tuple = (1, 2),
                 top_n_feeds: int = 20):
        """
        Args:
            max_tfidf_features: Maximum number of TF-IDF features
            ngram_range: N-gram range for TF-IDF
            top_n_feeds: Number of top feeds to one-hot encode
        """
        self.max_tfidf_features = max_tfidf_features
        self.ngram_range = ngram_range
        self.top_n_feeds = top_n_feeds
        self.tfidf_vectorizer = None
        self.char_vectorizer = None
        self.top_feeds = None

    def _derive_text_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """Derive title_word_count and word_count from text if not present"""
        X = X.copy()
        if 'title_word_count' not in X.columns and 'title' in X.columns:
            X['title_word_count'] = X['title'].fillna('').str.split().str.len()
        if 'word_count' not in X.columns and 'description' in X.columns:
            X['word_count'] = X['description'].fillna('').str.split().str.len()
        return X

    def fit(self, X: pd.DataFrame, y=None):
        """Fit feature extractors on training data"""
        # Combine title and description for TF-IDF
        text = (X['title'].fillna('') + ' ' + X['description'].fillna('')).values
        
        # Fit TF-IDF vectorizer
        # Adjust parameters for small datasets
        use_stopwords = 'english' if len(X) > 20 else None
        min_doc_freq = min(2, len(X)) if len(X) > 5 else 1
        
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=self.max_tfidf_features,
            ngram_range=self.ngram_range,
            stop_words=use_stopwords,
            min_df=min_doc_freq,
            max_df=0.8
        )
        self.tfidf_vectorizer.fit(text)
        
        # Fit character n-gram vectorizer for titles
        min_doc_freq_char = 1 if len(X) <= 5 else min(2, len(X))
        
        self.char_vectorizer = TfidfVectorizer(
            analyzer='char',
            ngram_range=(2, 3),
            max_features=100,
            min_df=min_doc_freq_char
        )
        self.char_vectorizer.fit(X['title'].fillna('').values)
        
        # Get top feeds for one-hot encoding
        self.top_feeds = X['feed_name'].value_counts().head(self.top_n_feeds).index.tolist()
        
        return self
    
    def transform(self, X: pd.DataFrame) -> np.ndarray:
        """Transform data to feature matrix"""
        X = self._derive_text_features(X)
        features = []

        # 1. TF-IDF features
        text = (X['title'].fillna('') + ' ' + X['description'].fillna('')).values
        tfidf_features = self.tfidf_vectorizer.transform(text).toarray()
        features.append(tfidf_features)
        
        # 2. Character n-gram features
        char_features = self.char_vectorizer.transform(X['title'].fillna('').values).toarray()
        features.append(char_features)
        
        # 3. Feed one-hot encoding
        feed_features = np.zeros((len(X), len(self.top_feeds)))
        for i, feed in enumerate(self.top_feeds):
            feed_features[:, i] = (X['feed_name'] == feed).astype(int)
        features.append(feed_features)
        
        # 4. Readability scores (simplified - Flesch Reading Ease)
        readability = self._compute_readability(X)
        features.append(readability.reshape(-1, 1))
        
        # 5. Sentiment scores (simplified - based on word patterns)
        sentiment = self._compute_sentiment(X)
        features.append(sentiment.reshape(-1, 1))

        return np.hstack(features)
    
    def _compute_readability(self, X: pd.DataFrame) -> np.ndarray:
        """Compute simplified readability score"""
        # Flesch Reading Ease approximation: based on avg sentence/word length
        word_count = X['word_count'].fillna(0).values
        title_word_count = X['title_word_count'].fillna(1).values
        
        # Approximate: shorter titles + moderate article length = easier
        score = 100 - (title_word_count * 2) - (word_count / 100)
        return np.clip(score, 0, 100)
    
    def _compute_sentiment(self, X: pd.DataFrame) -> np.ndarray:
        """Compute simplified sentiment score"""
        # Simple sentiment: count positive/negative words
        positive_words = {'good', 'great', 'best', 'amazing', 'excellent', 'love', 'awesome', 'breakthrough'}
        negative_words = {'bad', 'worst', 'terrible', 'awful', 'hate', 'fail', 'crisis', 'concern'}
        
        sentiment = np.zeros(len(X))
        for i, title in enumerate(X['title'].fillna('').str.lower()):
            words = set(title.split())
            pos_count = len(words & positive_words)
            neg_count = len(words & negative_words)
            sentiment[i] = pos_count - neg_count
        
        return sentiment


class BehavioralFeatureExtractor(BaseEstimator, TransformerMixin):
    """Extract user behavior patterns"""

    def __init__(self):
        self.feed_like_rates = None
        self.hour_like_rates = None
        self.dow_like_rates = None

    def _derive_time_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """Derive vote_hour and vote_day_of_week from voted_at if not present"""
        X = X.copy()
        if 'vote_hour' not in X.columns and 'voted_at' in X.columns:
            voted_at = pd.to_datetime(X['voted_at'], errors='coerce')
            X['vote_hour'] = voted_at.dt.hour.fillna(12).astype(int)
            X['vote_day_of_week'] = voted_at.dt.dayofweek.fillna(0).astype(int)
        return X

    def fit(self, X: pd.DataFrame, y=None):
        """Learn user preference patterns from training data"""
        X = self._derive_time_features(X)

        if y is not None:
            # Convert y to binary (like=1, others=0) for preference calculation
            is_like = (y == 2) if hasattr(y, '__iter__') else (y == 'like')

            # Feed preference rates
            feed_df = pd.DataFrame({'feed': X['feed_name'], 'like': is_like})
            self.feed_like_rates = feed_df.groupby('feed')['like'].mean().to_dict()

            # Hour preference rates
            hour_df = pd.DataFrame({'hour': X['vote_hour'], 'like': is_like})
            self.hour_like_rates = hour_df.groupby('hour')['like'].mean().to_dict()
            
            # Day of week preference rates
            dow_df = pd.DataFrame({'dow': X['vote_day_of_week'], 'like': is_like})
            self.dow_like_rates = dow_df.groupby('dow')['like'].mean().to_dict()
        else:
            # If no labels, use uniform rates
            self.feed_like_rates = {}
            self.hour_like_rates = {}
            self.dow_like_rates = {}
        
        return self
    
    def transform(self, X: pd.DataFrame) -> np.ndarray:
        """Transform to behavioral features"""
        X = self._derive_time_features(X)
        features = []

        # 1. Feed historical like rate
        feed_rates = X['feed_name'].map(self.feed_like_rates).fillna(0.5).values
        features.append(feed_rates.reshape(-1, 1))

        # 2. Hour historical like rate
        hour_rates = X['vote_hour'].map(self.hour_like_rates).fillna(0.5).values
        features.append(hour_rates.reshape(-1, 1))

        # 3. Day of week historical like rate
        dow_rates = X['vote_day_of_week'].map(self.dow_like_rates).fillna(0.5).values
        features.append(dow_rates.reshape(-1, 1))
        
        # 4. Reading speed (words per second if time available)
        reading_speed = X['word_count'].fillna(0) / (X['total_time'].fillna(1) + 1)
        features.append(reading_speed.values.reshape(-1, 1))
        
        return np.hstack(features)


class InteractionFeatureExtractor(BaseEstimator, TransformerMixin):
    """Extract interaction features between different attributes"""
    
    def __init__(self, top_n_feeds: int = 10):
        self.top_n_feeds = top_n_feeds
        self.top_feeds = None
        
    def fit(self, X: pd.DataFrame, y=None):
        """Learn which feeds to create interactions for"""
        self.top_feeds = X['feed_name'].value_counts().head(self.top_n_feeds).index.tolist()
        return self
    
    def transform(self, X: pd.DataFrame) -> np.ndarray:
        """Transform to interaction features"""
        features = []
        
        # 1. Reading time × feed interaction (for top feeds)
        for feed in self.top_feeds:
            is_feed = (X['feed_name'] == feed).astype(int)
            interaction = is_feed * X['reading_time_minutes'].fillna(0)
            features.append(interaction.values.reshape(-1, 1))
        
        # 2. Hour × weekend interaction
        hour_weekend = X['vote_hour'].fillna(12) * X['vote_is_weekend'].fillna(0)
        features.append(hour_weekend.values.reshape(-1, 1))
        
        # 3. Title length × has_media interaction
        title_media = X['title_char_count'].fillna(0) * X['has_media'].fillna(0)
        features.append(title_media.values.reshape(-1, 1))
        
        # 4. Days since published × open count interaction
        days_opens = X['days_since_published'].fillna(0) * X['open_count'].fillna(0)
        features.append(days_opens.values.reshape(-1, 1))
        
        return np.hstack(features)


class FeaturePipeline(BaseEstimator, TransformerMixin):
    """Combined feature extraction pipeline - scikit-learn compatible"""

    def __init__(self,
                 include_text: bool = True,
                 include_behavioral: bool = True,
                 include_interactions: bool = True):
        """
        Args:
            include_text: Include text features (TF-IDF, etc.)
            include_behavioral: Include behavioral features
            include_interactions: Include interaction features
        """
        self.include_text = include_text
        self.include_behavioral = include_behavioral
        self.include_interactions = include_interactions

        self.text_extractor = TextFeatureExtractor() if include_text else None
        self.behavioral_extractor = BehavioralFeatureExtractor() if include_behavioral else None
        self.interaction_extractor = InteractionFeatureExtractor() if include_interactions else None

    def _derive_all_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """Derive ALL missing columns from available data"""
        X = X.copy()

        # Text-based features
        if 'title_word_count' not in X.columns and 'title' in X.columns:
            X['title_word_count'] = X['title'].fillna('').str.split().str.len()
        if 'title_char_count' not in X.columns and 'title' in X.columns:
            X['title_char_count'] = X['title'].fillna('').str.len()
        if 'word_count' not in X.columns and 'description' in X.columns:
            X['word_count'] = X['description'].fillna('').str.split().str.len()

        # Time-based features from voted_at
        if 'voted_at' in X.columns:
            voted_at = pd.to_datetime(X['voted_at'], errors='coerce')
            if 'vote_hour' not in X.columns:
                X['vote_hour'] = voted_at.dt.hour.fillna(12).astype(int)
            if 'vote_day_of_week' not in X.columns:
                X['vote_day_of_week'] = voted_at.dt.dayofweek.fillna(0).astype(int)
            if 'vote_is_weekend' not in X.columns:
                X['vote_is_weekend'] = (voted_at.dt.dayofweek >= 5).astype(int)

        # Reading time (assume 200 words per minute)
        if 'reading_time_minutes' not in X.columns:
            wc = X['word_count'].fillna(0) if 'word_count' in X.columns else 0
            X['reading_time_minutes'] = wc / 200.0

        # Days since published
        if 'days_since_published' not in X.columns and 'published_at' in X.columns:
            published = pd.to_datetime(X['published_at'], errors='coerce')
            X['days_since_published'] = (pd.Timestamp.now() - published).dt.days.fillna(0)

        # Engagement features (default to 0 if missing)
        if 'open_count' not in X.columns:
            X['open_count'] = 0
        if 'total_time' not in X.columns:
            X['total_time'] = 0
        if 'has_media' not in X.columns:
            X['has_media'] = 0

        return X

    def fit(self, X: pd.DataFrame, y=None):
        """Fit all extractors"""
        X = self._derive_all_features(X)
        if self.include_text:
            self.text_extractor.fit(X, y)
        if self.include_behavioral:
            self.behavioral_extractor.fit(X, y)
        if self.include_interactions:
            self.interaction_extractor.fit(X, y)
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        """Transform using all extractors"""
        X = self._derive_all_features(X)
        features = []

        if self.include_text:
            text_features = self.text_extractor.transform(X)
            features.append(text_features)

        if self.include_behavioral:
            behavioral_features = self.behavioral_extractor.transform(X)
            features.append(behavioral_features)

        if self.include_interactions:
            interaction_features = self.interaction_extractor.transform(X)
            features.append(interaction_features)

        if not features:
            raise ValueError("At least one feature type must be included")

        return np.hstack(features)
    
    def get_feature_names(self) -> List[str]:
        """Get feature names (for interpretability)"""
        names = []
        
        if self.include_text:
            # TF-IDF feature names
            if self.text_extractor.tfidf_vectorizer:
                names.extend([f"tfidf_{name}" for name in 
                            self.text_extractor.tfidf_vectorizer.get_feature_names_out()])
            # Char n-gram names
            if self.text_extractor.char_vectorizer:
                names.extend([f"char_{name}" for name in 
                            self.text_extractor.char_vectorizer.get_feature_names_out()])
            # Feed names
            names.extend([f"feed_{feed}" for feed in self.text_extractor.top_feeds])
            # Other text features
            names.extend(['readability_score', 'sentiment_score'])
        
        if self.include_behavioral:
            names.extend(['feed_like_rate', 'hour_like_rate', 'dow_like_rate', 'reading_speed'])
        
        if self.include_interactions:
            names.extend([f"reading_time_x_{feed}" for feed in 
                         self.interaction_extractor.top_feeds])
            names.extend(['hour_x_weekend', 'title_x_media', 'days_x_opens'])
        
        return names


def test_feature_pipeline():
    """Test the feature pipeline with dummy data"""
    print("Testing Feature Pipeline...")
    
    # Create dummy data
    data = {
        'title': ['Great AI Breakthrough', 'Tech News Today', 'Science Update'],
        'description': ['Amazing discovery', 'Latest tech', 'New research'],
        'feed_name': ['TechCrunch', 'Wired', 'Nature'],
        'word_count': [500, 300, 800],
        'title_word_count': [3, 3, 2],
        'title_char_count': [20, 15, 14],
        'reading_time_minutes': [2.5, 1.5, 4.0],
        'has_media': [1, 0, 1],
        'vote_hour': [14, 16, 10],
        'vote_day_of_week': [1, 3, 5],
        'vote_is_weekend': [0, 0, 0],
        'days_since_published': [1, 5, 2],
        'open_count': [1, 0, 2],
        'total_time': [10, 0, 20]
    }
    df = pd.DataFrame(data)
    y = np.array([2, 1, 2])  # like, neutral, like
    
    # Test full pipeline
    pipeline = FeaturePipeline(
        include_text=True,
        include_behavioral=True,
        include_interactions=True
    )
    
    # Fit and transform
    pipeline.fit(df, y)
    features = pipeline.transform(df)
    
    print(f"✅ Feature matrix shape: {features.shape}")
    print(f"✅ No NaN values: {not np.isnan(features).any()}")
    print(f"✅ No infinite values: {not np.isinf(features).any()}")
    print(f"✅ Total features: {len(pipeline.get_feature_names())}")
    
    # Test individual extractors
    text_ext = TextFeatureExtractor()
    text_ext.fit(df)
    text_features = text_ext.transform(df)
    print(f"✅ Text features shape: {text_features.shape}")
    
    behavioral_ext = BehavioralFeatureExtractor()
    behavioral_ext.fit(df, y)
    behavioral_features = behavioral_ext.transform(df)
    print(f"✅ Behavioral features shape: {behavioral_features.shape}")
    
    interaction_ext = InteractionFeatureExtractor()
    interaction_ext.fit(df)
    interaction_features = interaction_ext.transform(df)
    print(f"✅ Interaction features shape: {interaction_features.shape}")
    
    print("\n✅ All tests passed!")
    return True


if __name__ == '__main__':
    test_feature_pipeline()
