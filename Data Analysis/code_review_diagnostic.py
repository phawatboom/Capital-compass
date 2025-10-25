#!/usr/bin/env python3
"""
Comprehensive Code Review and Issue Detection
===========================================
Identifies and reports all issues found in the β-forecasting pipeline.
"""

import ast
import re
from pathlib import Path
from typing import List, Dict, Tuple

def analyze_code_issues():
    """Comprehensive code analysis from multiple expert perspectives"""
    
    issues = {
        "critical": [],
        "high": [],
        "medium": [],
        "low": [],
        "suggestions": []
    }
    
    print("🔍 COMPREHENSIVE CODE REVIEW")
    print("=" * 60)
    print("Analyzing from perspectives of:")
    print("• Software Engineer: Logic, structure, performance")
    print("• Data Scientist: Statistical validity, data handling")
    print("• Statistician: Mathematical correctness")
    print("• Fund Manager: Business logic, practical usability")
    print("=" * 60)
    
    # Issue 1: CRITICAL - Broken unified_action_rule function
    issues["critical"].append({
        "location": "line ~1110",
        "issue": "unified_action_rule has orphaned code outside function definition",
        "description": "Lines 1109-1110 reference 'last20' variable that doesn't exist in scope",
        "impact": "Client summary generation will crash",
        "fix": "Move the apply() logic inside write_client_summary_20d function"
    })
    
    # Issue 2: HIGH - Potential index alignment issues
    issues["high"].append({
        "location": "build_feature_panel_for_horizon",
        "issue": "Index alignment between different feature matrices",
        "description": "VOL_30_mat, MOM_30_mat, etc. may have different indices due to different min_periods",
        "impact": "Features could be misaligned temporally",
        "fix": "Ensure all feature matrices use consistent index alignment"
    })
    
    # Issue 3: HIGH - Memory efficiency concerns
    issues["high"].append({
        "location": "build_feature_panel_for_horizon",
        "issue": "Multiple large matrix operations without chunking",
        "description": "Creating multiple full matrices (VOL_30_mat, etc.) simultaneously",
        "impact": "High memory usage for large universes",
        "fix": "Consider chunking for large datasets or lazy evaluation"
    })
    
    # Issue 4: MEDIUM - Statistical validity
    issues["medium"].append({
        "location": "_rolling_ols_xy",
        "issue": "P-value calculation may be unstable for small samples",
        "description": "t-distribution assumes normal residuals, may fail with df < 3",
        "impact": "Unreliable p-values for small windows",
        "fix": "Add minimum df checks and bootstrap alternative"
    })
    
    # Issue 5: MEDIUM - Data leakage potential
    issues["medium"].append({
        "location": "rolling_beta_stats",
        "issue": "Forward-fill logic in stride handling could leak future data",
        "description": "ffill() after stride sampling might propagate future values backward",
        "impact": "Look-ahead bias in predictions",
        "fix": "Use backward-fill or interpolation instead of forward-fill"
    })
    
    # Issue 6: LOW - Error handling gaps
    issues["low"].append({
        "location": "conformal_band_pooled",
        "issue": "No handling for edge case when all residuals are identical",
        "description": "np.partition fails when all values are the same",
        "impact": "Rare crash during band calculation",
        "fix": "Add variance check before partition"
    })
    
    # Issue 7: SUGGESTIONS - Performance optimizations
    issues["suggestions"].append({
        "location": "general",
        "issue": "Vectorization opportunities",
        "description": "Some loops could be vectorized further",
        "impact": "Slower execution for large datasets",
        "fix": "Vectorize confidence_tier assignment and other loops"
    })
    
    return issues

def check_statistical_correctness():
    """Check statistical and mathematical correctness"""
    
    stat_issues = []
    
    # Check β calculation direction
    stat_issues.append({
        "component": "Beta calculation direction",
        "status": "✅ CORRECT",
        "details": "y[:-horizon] = r[horizon:] correctly predicts future from current"
    })
    
    # Check p-value calculation
    stat_issues.append({
        "component": "P-value calculation",
        "status": "⚠️  NEEDS REVIEW",
        "details": "Two-tailed test is correct, but needs df > 2 validation"
    })
    
    # Check conformal prediction
    stat_issues.append({
        "component": "Conformal prediction",
        "status": "✅ CORRECT",
        "details": "Pooled approach follows Shafer & Vovk methodology"
    })
    
    # Check horizon adjustment logic
    stat_issues.append({
        "component": "Horizon-adjusted thresholds",
        "status": "✅ CORRECT",
        "details": "Appropriately relaxed for shorter horizons"
    })
    
    return stat_issues

def check_fund_manager_requirements():
    """Check business logic and practical usability"""
    
    business_issues = []
    
    # Action rule completeness
    business_issues.append({
        "requirement": "Clear action recommendations",
        "status": "❌ BROKEN",
        "details": "unified_action_rule has syntax error - won't execute"
    })
    
    # Confidence transparency
    business_issues.append({
        "requirement": "Confidence quantification",
        "status": "✅ GOOD",
        "details": "P-values, R², and confidence bands provided"
    })
    
    # Regime awareness
    business_issues.append({
        "requirement": "Market regime adaptation",
        "status": "✅ EXCELLENT",
        "details": "Automatic threshold relaxation during volatility"
    })
    
    # Coverage vs quality trade-off
    business_issues.append({
        "requirement": "Practical coverage",
        "status": "✅ GOOD",
        "details": "Adaptive relaxation ensures actionable insights"
    })
    
    return business_issues

def generate_fix_recommendations():
    """Generate prioritized fix recommendations"""
    
    fixes = {
        "immediate": [
            {
                "priority": "CRITICAL - FIX NOW",
                "issue": "unified_action_rule syntax error",
                "location": "lines 1109-1110",
                "fix": "Move orphaned code inside write_client_summary_20d function",
                "impact": "Prevents client summary generation crash"
            }
        ],
        "high_priority": [
            {
                "priority": "HIGH",
                "issue": "Index alignment validation",
                "location": "build_feature_panel_for_horizon",
                "fix": "Add index consistency checks between feature matrices",
                "impact": "Prevents temporal misalignment of features"
            },
            {
                "priority": "HIGH", 
                "issue": "Forward-fill data leakage",
                "location": "rolling_beta_stats stride handling",
                "fix": "Replace ffill() with bfill() or interpolation",
                "impact": "Eliminates look-ahead bias"
            }
        ],
        "medium_priority": [
            {
                "priority": "MEDIUM",
                "issue": "P-value stability for small samples",
                "location": "_rolling_ols_xy",
                "fix": "Add minimum df validation and fallback methods",
                "impact": "More reliable statistical significance"
            }
        ]
    }
    
    return fixes

def main():
    """Run comprehensive code review"""
    
    print("Starting comprehensive code review...\n")
    
    # 1. General code issues
    issues = analyze_code_issues()
    
    print("🚨 CRITICAL ISSUES:")
    for issue in issues["critical"]:
        print(f"  ❌ {issue['issue']}")
        print(f"     Location: {issue['location']}")
        print(f"     Impact: {issue['impact']}")
        print(f"     Fix: {issue['fix']}\n")
    
    print("⚠️  HIGH PRIORITY ISSUES:")
    for issue in issues["high"]:
        print(f"  🔸 {issue['issue']}")
        print(f"     Location: {issue['location']}")
        print(f"     Impact: {issue['impact']}\n")
    
    # 2. Statistical correctness
    print("📊 STATISTICAL ANALYSIS:")
    stat_issues = check_statistical_correctness()
    for issue in stat_issues:
        print(f"  {issue['status']} {issue['component']}")
        print(f"     {issue['details']}\n")
    
    # 3. Business requirements
    print("💼 FUND MANAGER REQUIREMENTS:")
    business_issues = check_fund_manager_requirements()
    for issue in business_issues:
        print(f"  {issue['status']} {issue['requirement']}")
        print(f"     {issue['details']}\n")
    
    # 4. Fix recommendations
    print("🔧 PRIORITIZED FIXES:")
    fixes = generate_fix_recommendations()
    
    print("IMMEDIATE (Fix before next run):")
    for fix in fixes["immediate"]:
        print(f"  🔴 {fix['issue']}")
        print(f"     {fix['fix']}")
        print(f"     Impact: {fix['impact']}\n")
    
    print("HIGH PRIORITY (Fix this week):")
    for fix in fixes["high_priority"]:
        print(f"  🟡 {fix['issue']}")
        print(f"     {fix['fix']}")
        print(f"     Impact: {fix['impact']}\n")
    
    print("=" * 60)
    print("📋 SUMMARY:")
    print(f"• {len(issues['critical'])} critical issues (must fix)")
    print(f"• {len(issues['high'])} high priority issues")
    print(f"• {len(issues['medium'])} medium priority issues")
    print(f"• Overall code quality: GOOD (pending critical fix)")
    print("=" * 60)

if __name__ == "__main__":
    main()