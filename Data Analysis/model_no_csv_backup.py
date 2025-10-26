"""
Compatibility layer for model_no_csv imports
This file re-exports functions from one_model_for_all_stock.py
"""

from one_model_for_all_stock import (
    _coerce_date,
    load_mxus_returns, 
    run_pipeline_for_horizon,
    aggregate_to_period_returns,
    rich_features_from_returns,
    _cs_percentile_rank_wide,
    add_cross_sectional_ranks
)

# Make all functions available at module level
__all__ = [
    '_coerce_date',
    'load_mxus_returns', 
    'run_pipeline_for_horizon',
    'aggregate_to_period_returns',
    'rich_features_from_returns',
    '_cs_percentile_rank_wide',
    'add_cross_sectional_ranks'
]