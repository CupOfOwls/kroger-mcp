"""
Centralized configuration for analytics and predictions.

Provides configurable thresholds, EWMA parameters, and prediction buffers
with persistence to kroger_preferences.json.
"""

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

# Config file location (same directory as other preferences)
CONFIG_FILE = "kroger_preferences.json"


@dataclass
class PredictionConfig:
    """Configuration for prediction and categorization parameters."""

    # EWMA parameters
    ewma_alpha: float = 0.3  # Decay factor (0.3 better than 0.5 for groceries)

    # Buffer multipliers (std dev multiplier for safety margin)
    buffer_routine: float = 1.0   # Don't run out of essentials
    buffer_regular: float = 0.5   # Moderate safety
    buffer_treat: float = 0.0     # No buffer needed

    # Category thresholds (in days between purchases)
    routine_max_days: int = 14    # ≤14 days = routine
    regular_max_days: int = 60    # 15-60 days = regular
    seasonality_threshold: float = 0.7  # >0.7 seasonality = treat

    # Urgency thresholds
    urgency_critical: float = 0.9
    urgency_high: float = 0.7
    urgency_medium: float = 0.4

    # Prediction parameters
    min_purchases_for_prediction: int = 2
    max_confidence_purchases: int = 10  # Confidence maxes at this many

    def get_buffer_for_category(self, category: str) -> float:
        """Get buffer multiplier for a category."""
        buffers = {
            'routine': self.buffer_routine,
            'regular': self.buffer_regular,
            'treat': self.buffer_treat,
        }
        return buffers.get(category, 0.0)


# Global config instance (lazy loaded)
_config: Optional[PredictionConfig] = None


def load_config() -> PredictionConfig:
    """
    Load configuration from file or return defaults.

    Returns:
        PredictionConfig instance
    """
    global _config

    if _config is not None:
        return _config

    _config = PredictionConfig()

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)

            # Extract prediction config if present
            pred_config = data.get('prediction_config', {})

            # Update config with saved values
            if 'ewma_alpha' in pred_config:
                _config.ewma_alpha = float(pred_config['ewma_alpha'])
            if 'buffer_routine' in pred_config:
                _config.buffer_routine = float(pred_config['buffer_routine'])
            if 'buffer_regular' in pred_config:
                _config.buffer_regular = float(pred_config['buffer_regular'])
            if 'buffer_treat' in pred_config:
                _config.buffer_treat = float(pred_config['buffer_treat'])
            if 'routine_max_days' in pred_config:
                _config.routine_max_days = int(pred_config['routine_max_days'])
            if 'regular_max_days' in pred_config:
                _config.regular_max_days = int(pred_config['regular_max_days'])
            if 'seasonality_threshold' in pred_config:
                _config.seasonality_threshold = float(
                    pred_config['seasonality_threshold'])
            if 'urgency_critical' in pred_config:
                _config.urgency_critical = float(pred_config['urgency_critical'])
            if 'urgency_high' in pred_config:
                _config.urgency_high = float(pred_config['urgency_high'])
            if 'urgency_medium' in pred_config:
                _config.urgency_medium = float(pred_config['urgency_medium'])
            if 'min_purchases_for_prediction' in pred_config:
                _config.min_purchases_for_prediction = int(
                    pred_config['min_purchases_for_prediction'])

        except (json.JSONDecodeError, IOError, KeyError, ValueError):
            # On any error, use defaults
            _config = PredictionConfig()

    return _config


def save_config(config: PredictionConfig) -> Dict[str, Any]:
    """
    Save configuration to file.

    Args:
        config: PredictionConfig to save

    Returns:
        Dict with success status
    """
    global _config

    # Load existing preferences to preserve other settings
    existing = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = {}

    # Update prediction config section
    existing['prediction_config'] = asdict(config)

    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(existing, f, indent=2)

        _config = config
        return {'success': True, 'config': asdict(config)}
    except IOError as e:
        return {'success': False, 'error': str(e)}


def update_config(**kwargs) -> Dict[str, Any]:
    """
    Update specific configuration values.

    Args:
        **kwargs: Configuration fields to update

    Returns:
        Dict with success status and updated config
    """
    config = load_config()

    # Update provided fields
    valid_fields = {
        'ewma_alpha', 'buffer_routine', 'buffer_regular', 'buffer_treat',
        'routine_max_days', 'regular_max_days', 'seasonality_threshold',
        'urgency_critical', 'urgency_high', 'urgency_medium',
        'min_purchases_for_prediction', 'max_confidence_purchases'
    }

    updated = []
    for key, value in kwargs.items():
        if key in valid_fields and value is not None:
            setattr(config, key, value)
            updated.append(key)

    if updated:
        result = save_config(config)
        result['updated_fields'] = updated
        return result

    return {'success': True, 'message': 'No changes made', 'config': asdict(config)}


def reset_config() -> Dict[str, Any]:
    """
    Reset configuration to defaults.

    Returns:
        Dict with success status
    """
    global _config
    _config = PredictionConfig()
    return save_config(_config)


def get_config_summary() -> Dict[str, Any]:
    """
    Get current configuration as a summary.

    Returns:
        Dict with all config values
    """
    config = load_config()
    return {
        'ewma': {
            'alpha': config.ewma_alpha,
            'description': 'Decay factor for weighted average (lower = more weight on recent)'
        },
        'buffers': {
            'routine': config.buffer_routine,
            'regular': config.buffer_regular,
            'treat': config.buffer_treat,
            'description': 'Std dev multiplier for safety margin by category'
        },
        'category_thresholds': {
            'routine_max_days': config.routine_max_days,
            'regular_max_days': config.regular_max_days,
            'seasonality_threshold': config.seasonality_threshold,
            'description': 'Days between purchases for category classification'
        },
        'urgency_thresholds': {
            'critical': config.urgency_critical,
            'high': config.urgency_high,
            'medium': config.urgency_medium,
            'description': 'Urgency score thresholds for labels'
        },
        'prediction': {
            'min_purchases': config.min_purchases_for_prediction,
            'max_confidence_purchases': config.max_confidence_purchases,
            'description': 'Minimum data requirements for predictions'
        }
    }
