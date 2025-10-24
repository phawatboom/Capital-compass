import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def create_large_test_dataset():
    """Create a test dataset with sufficient historical data for feature generation"""
    
    # Generate 90 trading days (about 4 months)
    start_date = datetime(2022, 1, 3)
    dates = []
    current_date = start_date
    
    # Generate weekdays only (trading days)
    while len(dates) < 90:
        if current_date.weekday() < 5:  # Monday=0, Friday=4
            dates.append(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(days=1)
    
    # Stock tickers and starting prices
    stocks = {
        'AAPL': 180.0,
        'MSFT': 330.0,
        'GOOGL': 2800.0,
        'AMZN': 3400.0,
        'TSLA': 1100.0,
        'NVDA': 280.0,
        'META': 320.0,
        'JPM': 165.0,
        'JNJ': 170.0,
        'XOM': 60.0,
        'PG': 160.0,
        'KO': 59.0,
        'HD': 400.0,
        'V': 210.0,
        'UNH': 500.0
    }
    
    data = []
    
    for ticker, start_price in stocks.items():
        price = start_price
        
        for i, date in enumerate(dates):
            # Generate realistic price movements
            # Add some trends and volatility
            daily_return = np.random.normal(0.0005, 0.02)  # Small positive drift with 2% daily volatility
            
            # Add some correlation patterns
            if ticker in ['AAPL', 'MSFT', 'GOOGL']:  # Tech stocks more correlated
                if i > 0:
                    daily_return += np.random.normal(0, 0.005)
            
            # Add some mean reversion
            if price > start_price * 1.2:
                daily_return -= 0.001
            elif price < start_price * 0.8:
                daily_return += 0.001
            
            price = price * (1 + daily_return)
            price = round(price, 2)
            
            data.append({
                'Date': date,
                'Ticker': ticker,
                'Close': price
            })
    
    return pd.DataFrame(data)

# Create the dataset
print("Creating large test dataset with 90 trading days...")
df = create_large_test_dataset()

# Save to CSV
df.to_csv('test_data_large.csv', index=False)

print(f"✓ Created test_data_large.csv with {len(df)} rows")
print(f"✓ Date range: {df['Date'].min()} to {df['Date'].max()}")
print(f"✓ Unique tickers: {df['Ticker'].nunique()}")
print(f"✓ Trading days per stock: {len(df) // df['Ticker'].nunique()}")
print("\nSample data:")
print(df.head(10))