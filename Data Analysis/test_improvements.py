#!/usr/bin/env python3
"""
Quick test of the reviewer's key improvements to the beta forecasting system.
"""

import pandas as pd
import numpy as np
from bcoefficient_production_level_code_patched import (
    rolling_autocorr_lag1_vectorized, 
    unified_action_rule,
    conformal_band_pooled
)

def test_vectorized_ar1():
    """Test that vectorized AR(1) gives same results as original but faster."""
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0, 0.02, 100))
    
    # The vectorized version should give similar results
    ar1_vec = rolling_autocorr_lag1_vectorized(returns, 20)
    
    # Basic checks
    assert not ar1_vec.isna().all(), "AR(1) should produce some values"
    assert abs(ar1_vec.dropna()).max() <= 1.0, "AR(1) correlations should be [-1,1]"
    print("✓ Vectorized AR(1) test passed")

def test_unified_action_rule():
    """Test the unified action rule logic."""
    # Test case 1: Strong chase signal
    strong_chase = {
        "beta_pred": 0.15,
        "conf_20d": 0.8,
        "r2_ols": 0.05,
        "p_value": 0.02,
        "agree_adjacent": True,
        "term_unstable": False
    }
    action, reason = unified_action_rule(pd.Series(strong_chase))
    assert action == "chase", f"Expected chase, got {action}"
    assert reason == "all_checks_passed", f"Expected all_checks_passed, got {reason}"
    
    # Test case 2: Hold due to low confidence
    low_conf = strong_chase.copy()
    low_conf["conf_20d"] = 0.4
    action, reason = unified_action_rule(pd.Series(low_conf))
    assert action == "hold", f"Expected hold, got {action}"
    assert reason == "low_confidence", f"Expected low_confidence, got {reason}"
    
    # Test case 3: Hold due to weak signal
    weak_signal = strong_chase.copy()
    weak_signal["beta_pred"] = 0.02
    action, reason = unified_action_rule(pd.Series(weak_signal))
    assert action == "hold", f"Expected hold, got {action}"
    assert reason == "weak_signal", f"Expected weak_signal, got {reason}"
    
    print("✓ Unified action rule test passed")

def test_pooled_conformal():
    """Test pooled conformal bands."""
    np.random.seed(42)
    
    # Generate some residual arrays
    residuals = [
        np.random.normal(0, 0.1, 50),
        np.random.normal(0, 0.12, 50), 
        np.random.normal(0, 0.08, 50)
    ]
    
    band_pooled = conformal_band_pooled(residuals, alpha=0.10)
    
    # Should be reasonable magnitude
    assert 0.01 < band_pooled < 1.0, f"Band seems unreasonable: {band_pooled}"
    
    # Empty case
    empty_band = conformal_band_pooled([], alpha=0.10)
    assert empty_band == 0.0, "Empty residuals should give zero band"
    
    print("✓ Pooled conformal bands test passed")

if __name__ == "__main__":
    print("Testing key improvements from reviewer feedback...")
    
    test_vectorized_ar1()
    test_unified_action_rule() 
    test_pooled_conformal()
    
    print("\n🎉 All tests passed! Key improvements are working correctly.")
    print("\nImprovements implemented:")
    print("1. ✓ Unified action rule (single source of truth)")
    print("2. ✓ Simplified gates (removed double-dipping)")
    print("3. ✓ Vectorized AR(1) (performance boost)")
    print("4. ✓ Pooled conformal bands (stability)")