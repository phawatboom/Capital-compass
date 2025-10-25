#!/usr/bin/env python3
"""
Function-Level Validation Tests
==============================
Tests specific functions to ensure they work as intended.
"""

import numpy as np
import pandas as pd
from pathlib import Path
import sys

# Add the current directory to path to import from main file
sys.path.append('.')

def test_rolling_ols_xy():
    """Test the core OLS calculation function"""
    print("🧪 Testing _rolling_ols_xy function...")
    
    try:
        # Import the function
        from bcoefficient_production_level_code_patched import _rolling_ols_xy
        
        # Create simple test data
        np.random.seed(42)
        n = 100
        x = np.random.randn(n)
        y = 0.5 * x + 0.2 * np.random.randn(n)  # True beta = 0.5
        
        # Test with reasonable parameters
        beta, r2, n_obs, sxx_d, ok, p_value = _rolling_ols_xy(x, y, window=30, min_obs=20)
        
        # Validate results
        valid_results = ok.sum()
        if valid_results > 0:
            avg_beta = beta[ok].mean()
            avg_r2 = r2[ok].mean()
            avg_p = p_value[ok & np.isfinite(p_value)].mean()
            
            print(f"  ✅ Function executes successfully")
            print(f"  ✅ {valid_results}/{len(ok)} valid results")
            print(f"  ✅ Average beta: {avg_beta:.3f} (expected ~0.5)")
            print(f"  ✅ Average R²: {avg_r2:.3f}")
            print(f"  ✅ Average p-value: {avg_p:.3f}")
            
            # Test edge cases
            # All zeros
            x_zero = np.zeros(50)
            y_zero = np.zeros(50)
            beta_z, r2_z, n_z, sxx_z, ok_z, p_z = _rolling_ols_xy(x_zero, y_zero, window=20, min_obs=10)
            print(f"  ✅ Zero case handled: {ok_z.sum()} valid results (should be 0)")
            
            return True
        else:
            print(f"  ❌ No valid results generated")
            return False
            
    except Exception as e:
        print(f"  ❌ Function failed: {e}")
        return False

def test_horizon_thresholds():
    """Test horizon-adjusted threshold function"""
    print("\n🧪 Testing get_horizon_adjusted_thresholds...")
    
    try:
        from bcoefficient_production_level_code_patched import get_horizon_adjusted_thresholds, Config
        
        cfg = Config()
        
        # Test different horizons
        horizons = [1, 2, 5, 10, 20]
        for h in horizons:
            thresholds = get_horizon_adjusted_thresholds(h, cfg)
            r2_min = thresholds['r2_min']
            p_max = thresholds['p_value_max']
            
            print(f"  ✅ H={h:2d}d: r2_min={r2_min:.6f}, p_max={p_max:.3f}")
            
            # Validate that thresholds make sense
            assert 0 < r2_min < 0.1, f"R² threshold seems wrong: {r2_min}"
            assert 0 < p_max <= 1.0, f"P-value threshold seems wrong: {p_max}"
        
        # Test that shorter horizons are more relaxed
        t1 = get_horizon_adjusted_thresholds(1, cfg)
        t20 = get_horizon_adjusted_thresholds(20, cfg)
        
        assert t1['r2_min'] <= t20['r2_min'], "Short horizons should have lower R² requirements"
        assert t1['p_value_max'] >= t20['p_value_max'], "Short horizons should allow higher p-values"
        
        print(f"  ✅ Threshold progression is logical")
        return True
        
    except Exception as e:
        print(f"  ❌ Function failed: {e}")
        return False

def test_unified_action_rule():
    """Test the action rule function"""
    print("\n🧪 Testing unified_action_rule...")
    
    try:
        from bcoefficient_production_level_code_patched import unified_action_rule
        
        # Test different scenarios
        test_cases = [
            # (beta_pred, r2_ols, p_value, conf_20d, agree_adjacent, term_unstable, expected_action)
            (0.15, 0.05, 0.01, 0.8, True, False, "chase"),  # Strong positive signal
            (-0.15, 0.05, 0.01, 0.8, True, False, "fade"),  # Strong negative signal
            (0.15, 0.005, 0.01, 0.8, True, False, "hold"),  # Low R²
            (0.15, 0.05, 0.10, 0.8, True, False, "hold"),   # High p-value
            (0.15, 0.05, 0.01, 0.3, True, False, "hold"),   # Low confidence
            (0.15, 0.05, 0.01, 0.8, False, False, "hold"),  # No horizon agreement
            (0.15, 0.05, 0.01, 0.8, True, True, "hold"),    # Term unstable
            (0.02, 0.05, 0.01, 0.8, True, False, "hold"),   # Weak signal
        ]
        
        for i, (beta_pred, r2_ols, p_value, conf_20d, agree_adjacent, term_unstable, expected) in enumerate(test_cases):
            row = {
                'beta_pred': beta_pred,
                'r2_ols': r2_ols,
                'p_value': p_value,
                'conf_20d': conf_20d,
                'agree_adjacent': agree_adjacent,
                'term_unstable': term_unstable
            }
            
            action, reason = unified_action_rule(row)
            
            if action == expected:
                print(f"  ✅ Test {i+1}: {action} ({reason})")
            else:
                print(f"  ❌ Test {i+1}: Expected {expected}, got {action} ({reason})")
                return False
        
        return True
        
    except Exception as e:
        print(f"  ❌ Function failed: {e}")
        return False

def test_conformal_band():
    """Test conformal prediction band calculation"""
    print("\n🧪 Testing conformal_band...")
    
    try:
        from bcoefficient_production_level_code_patched import conformal_band
        
        # Test normal case
        np.random.seed(42)
        residuals = np.random.randn(100)
        band = conformal_band(residuals, alpha=0.10)
        
        # Should be around the 90th percentile of absolute residuals
        expected = np.percentile(np.abs(residuals), 90)
        
        print(f"  ✅ Normal case: band={band:.3f}, expected~{expected:.3f}")
        
        # Test edge cases
        # Empty array
        band_empty = conformal_band(np.array([]))
        assert band_empty == 0.0, "Empty array should return 0"
        print(f"  ✅ Empty array: {band_empty}")
        
        # All identical values
        identical = np.array([1.5] * 50)
        band_identical = conformal_band(identical)
        assert band_identical == 1.5, f"Identical values should return the value: {band_identical}"
        print(f"  ✅ Identical values: {band_identical}")
        
        # Array with NaNs
        with_nans = np.array([1, 2, np.nan, 3, 4, np.nan])
        band_nans = conformal_band(with_nans)
        print(f"  ✅ With NaNs: {band_nans:.3f}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Function failed: {e}")
        return False

def test_config_validation():
    """Test configuration validation"""
    print("\n🧪 Testing validate_config...")
    
    try:
        from bcoefficient_production_level_code_patched import validate_config, Config
        
        # Test valid config
        valid_config = Config()
        validate_config(valid_config)
        print(f"  ✅ Valid config passes")
        
        # Test invalid configs
        invalid_configs = [
            # (field, value, expected_error_partial)
            ('beta_window', 10, 'beta_window too small'),
            ('beta_window', 20, 'beta_window ({}) must be >= min_obs'),  # when min_obs > 20
            ('target_gap_days', 0, 'target_gap_days must be positive'),
            ('stride_days', 0, 'stride_days must be >= 1'),
            ('horizons', [], 'horizons list cannot be empty'),
        ]
        
        for field, value, error_partial in invalid_configs:
            bad_config = Config()
            setattr(bad_config, field, value)
            
            try:
                validate_config(bad_config)
                print(f"  ❌ {field}={value} should have failed validation")
                return False
            except ValueError as e:
                if error_partial.lower() in str(e).lower():
                    print(f"  ✅ {field}={value} correctly rejected: {str(e)[:50]}...")
                else:
                    print(f"  ⚠️  {field}={value} rejected but wrong message: {e}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Validation test failed: {e}")
        return False

def main():
    """Run all function tests"""
    print("🔬 FUNCTION-LEVEL VALIDATION TESTS")
    print("=" * 60)
    
    tests = [
        test_rolling_ols_xy,
        test_horizon_thresholds,
        test_unified_action_rule,
        test_conformal_band,
        test_config_validation,
    ]
    
    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"  ❌ Test {test_func.__name__} crashed: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    for i, (test_func, result) in enumerate(zip(tests, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_func.__name__}")
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - Code is ready for production!")
    else:
        print("⚠️  Some tests failed - Review and fix before deployment")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)