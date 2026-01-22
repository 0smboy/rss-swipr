"""
Model Manager for RSS Swipr app.
Handles model upload, validation, and switching.
"""
import pickle
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

# Root directory (parent of src/)
ROOT_DIR = Path(__file__).parent.parent

# Add ml directory to path for feature_engineering module (required for pickle deserialization)
ML_DIR = ROOT_DIR / 'ml'
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


class ModelManager:
    """Manages ML model uploads and switching."""

    # Paths relative to root directory
    MODELS_DIR = ROOT_DIR / 'ml' / 'models' / 'uploads'
    DEFAULT_MODEL = ROOT_DIR / 'ml' / 'models' / 'hybrid_rf.pkl'

    def __init__(self, db):
        """Initialize with tracking database reference."""
        self.db = db
        self.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._current_model = None
        self._current_model_data = None

    def _to_native(self, val):
        """Convert numpy types to native Python types for JSON serialization."""
        if val is None:
            return None
        # Handle numpy types
        if hasattr(val, 'item'):  # numpy scalars have .item()
            return val.item()
        if isinstance(val, (list, tuple)):
            return [self._to_native(v) for v in val]
        return val

    def validate_model(self, pkl_data: bytes) -> Tuple[bool, Dict[str, Any]]:
        """Validate an uploaded pickle file contains a valid model.

        Returns:
            (is_valid, info_or_error)
        """
        try:
            model_data = pickle.loads(pkl_data)

            # Check for required keys
            if 'model' not in model_data:
                return False, {'error': "Missing 'model' key in pickle"}

            model = model_data['model']

            # Check for predict_proba method
            if not hasattr(model, 'predict_proba'):
                return False, {'error': "Model must have predict_proba method"}

            # Check for classes
            if not hasattr(model, 'classes_'):
                return False, {'error': "Model must have classes_ attribute"}

            # Get model info - convert numpy types to native Python types
            classes = list(model.classes_) if hasattr(model, 'classes_') else None
            info = {
                'model_type': type(model).__name__,
                'classes': self._to_native(classes),
                'has_feature_pipeline': 'feature_pipeline' in model_data,
                'has_scaler': 'scaler' in model_data,
                'n_features': self._to_native(model_data.get('results', {}).get('n_features')),
                'roc_auc': self._to_native(model_data.get('results', {}).get('mean_roc_auc')),
                'n_samples': self._to_native(model_data.get('results', {}).get('n_samples')),
                'saved_at': model_data.get('saved_at'),
            }

            return True, info

        except Exception as e:
            return False, {'error': f"Invalid pickle file: {str(e)}"}

    def save_uploaded_model(self, pkl_data: bytes, name: str) -> Tuple[bool, Dict[str, Any]]:
        """Save an uploaded model file and register it.

        Returns:
            (success, info_or_error)
        """
        # Validate first
        is_valid, info = self.validate_model(pkl_data)
        if not is_valid:
            return False, info

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in name)
        filename = f"{timestamp}_{safe_name}.pkl"
        filepath = self.MODELS_DIR / filename

        # Save file
        try:
            with open(filepath, 'wb') as f:
                f.write(pkl_data)
        except Exception as e:
            return False, {'error': f"Failed to save model: {str(e)}"}

        # Register in database
        metadata_json = json.dumps(info)
        model_id = self.db.save_model(name, filename, metadata_json)

        return True, {
            'model_id': model_id,
            'filename': filename,
            'info': info
        }

    def load_model(self, model_id: int = None) -> Optional[Dict[str, Any]]:
        """Load a model by ID, or the active model, or the default model.

        Returns the model data dict or None.
        """
        filepath = None

        if model_id:
            # Load specific model
            model_record = self.db.get_model_by_id(model_id)
            if model_record:
                filepath = self.MODELS_DIR / model_record['filename']
        else:
            # Try active model
            active = self.db.get_active_model()
            if active:
                filepath = self.MODELS_DIR / active['filename']

        # Fall back to default model
        if not filepath or not filepath.exists():
            filepath = self.DEFAULT_MODEL

        if not filepath.exists():
            return None

        try:
            with open(filepath, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return None

    def get_current_model(self) -> Optional[Dict[str, Any]]:
        """Get the currently loaded model (cached)."""
        if self._current_model_data is None:
            self._current_model_data = self.load_model()
        return self._current_model_data

    def reload_model(self) -> Optional[Dict[str, Any]]:
        """Force reload the current model."""
        self._current_model_data = self.load_model()
        return self._current_model_data

    def activate_model(self, model_id: int) -> bool:
        """Activate a model and reload it."""
        success = self.db.activate_model(model_id)
        if success:
            self.reload_model()
        return success

    def delete_model(self, model_id: int) -> Tuple[bool, str]:
        """Delete a model file and registry entry."""
        model_record = self.db.get_model_by_id(model_id)
        if not model_record:
            return False, "Model not found"

        # Don't allow deleting active model
        if model_record['is_active']:
            return False, "Cannot delete active model"

        # Delete file
        filepath = self.MODELS_DIR / model_record['filename']
        if filepath.exists():
            try:
                os.remove(filepath)
            except Exception as e:
                return False, f"Failed to delete file: {str(e)}"

        # Delete from database
        self.db.delete_model(model_id)
        return True, "Model deleted"

    def list_models(self) -> list:
        """Get all registered models with parsed metadata."""
        models = self.db.get_models()
        for model in models:
            if model.get('metadata'):
                try:
                    model['metadata'] = json.loads(model['metadata'])
                except Exception:
                    pass
        return models

    def get_model_status(self) -> Dict[str, Any]:
        """Get current model status info."""
        active = self.db.get_active_model()
        models = self.list_models()

        # Check if using default model
        using_default = active is None

        return {
            'active_model': active,
            'using_default': using_default,
            'default_model_path': str(self.DEFAULT_MODEL),
            'default_exists': self.DEFAULT_MODEL.exists(),
            'total_models': len(models),
            'models': models
        }
