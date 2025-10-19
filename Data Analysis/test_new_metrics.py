#!/usr/bin/env python3
"""
Quick test script to verify the new evaluation metrics are working correctly.
"""

import pandas as pd
import numpy as np
from pathlib import Path

def test_metrics_output():
    """Test that the new metrics files are being generated correctly"""
    
    output_dir = Path("./outputs")
    
    # Check for new metrics files
    horizons = [1, 2, 5, 10, 20]
    
    print("🔍 Testing new evaluation metrics...")
    print("=" * 50)
    
    for horizon in horizons:
        # Check if metrics files exist
        metrics_file = output_dir / f"metrics_{horizon}d.csv"
        folds_file = output_dir / f"metrics_{horizon}d_folds.csv"
        per_ticker_file = output_dir / f"metrics_{horizon}d_per_ticker.csv"
        
        print(f"\n📊 Horizon {horizon}d:")
        
        if metrics_file.exists():
            df = pd.read_csv(metrics_file)
            if not df.empty:
                row = df.iloc[0]
                print(f"  ✅ Overall metrics:")
                print(f"     • Directional accuracy: {row.get('directional_accuracy', 'N/A'):.1%}")
                print(f"     • Precision@action: {row.get('precision_at_action', 'N/A'):.1%}")
                print(f"     • MAE: {row.get('mae', 'N/A'):.4f}")
                print(f"     • RMSE: {row.get('rmse', 'N/A'):.4f}")
                print(f"     • Coverage 90%: {row.get('coverage_90', 'N/A'):.1%}")
                print(f"     • Correlation: {row.get('correlation', 'N/A'):.3f}")
                if 'interval_score_90' in row:
                    print(f"     • Interval Score: {row['interval_score_90']:.4f}")
                print(f"     • Total predictions: {row.get('total_predictions', 'N/A')}")
                print(f"     • Strong signals: {row.get('strong_signal_predictions', 'N/A')}")
        else:
            print(f"  ❌ Missing: {metrics_file.name}")
        
        if folds_file.exists():
            df_folds = pd.read_csv(folds_file)
            print(f"  ✅ Fold metrics: {len(df_folds)} folds tracked")
        else:
            print(f"  ❌ Missing: {folds_file.name}")
            
        if per_ticker_file.exists():
            df_ticker = pd.read_csv(per_ticker_file)
            print(f"  ✅ Per-ticker metrics: {len(df_ticker)} tickers analyzed")
            
            # Show top performers by directional accuracy
            if not df_ticker.empty and 'directional_accuracy' in df_ticker.columns:
                top_performers = df_ticker.nlargest(3, 'directional_accuracy')
                print(f"     Top performers:")
                for idx, ticker_row in top_performers.iterrows():
                    print(f"       {ticker_row.name}: {ticker_row['directional_accuracy']:.1%} accuracy")
        else:
            print(f"  ❌ Missing: {per_ticker_file.name}")

def analyze_decision_metrics():
    """Analyze the decision-aligned metrics across horizons"""
    
    print("\n" + "=" * 50)
    print("📈 DECISION-ALIGNED METRICS ANALYSIS")
    print("=" * 50)
    
    output_dir = Path("./outputs")
    horizon_data = []
    
    for horizon in [1, 2, 5, 10, 20]:
        metrics_file = output_dir / f"metrics_{horizon}d.csv"
        if metrics_file.exists():
            df = pd.read_csv(metrics_file)
            if not df.empty:
                horizon_data.append(df.iloc[0])
    
    if horizon_data:
        summary_df = pd.DataFrame(horizon_data)
        
        print("\n🎯 Key Business Metrics by Horizon:")
        print("-" * 40)
        for _, row in summary_df.iterrows():
            h = int(row['horizon'])
            dir_acc = row.get('directional_accuracy', 0)
            prec_action = row.get('precision_at_action', 0)
            strong_pct = (row.get('strong_signal_predictions', 0) / 
                         max(row.get('total_predictions', 1), 1)) * 100
            
            print(f"H={h:2d}d: Dir={dir_acc:.1%} | Prec@Action={prec_action:.1%} | Strong={strong_pct:.1f}%")
        
        # Find best performing horizon
        if 'precision_at_action' in summary_df.columns:
            best_horizon = summary_df.loc[summary_df['precision_at_action'].idxmax(), 'horizon']
            best_prec = summary_df['precision_at_action'].max()
            print(f"\n🏆 Best horizon for trading: {int(best_horizon)}d ({best_prec:.1%} precision)")
    
    else:
        print("❌ No metrics data found. Run the pipeline first!")

def main():
    """Main test function"""
    print("🧪 TESTING NEW EVALUATION METRICS")
    print("=" * 50)
    print("This script analyzes the new comprehensive evaluation metrics")
    print("added to your β forecasting pipeline.\n")
    
    try:
        test_metrics_output()
        analyze_decision_metrics()
        
        print("\n" + "=" * 50)
        print("✅ METRICS TEST COMPLETE")
        print("=" * 50)
        print("\nNext steps:")
        print("1. Run your main pipeline to generate fresh metrics")
        print("2. Review the decision-aligned metrics for business insights")
        print("3. Use per-ticker metrics to identify your best performers")
        print("4. Monitor fold metrics for model stability over time")
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        print("\nMake sure to run your main pipeline first to generate metrics files.")

if __name__ == "__main__":
    main()