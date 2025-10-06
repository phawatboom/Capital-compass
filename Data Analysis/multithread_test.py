from joblib import Parallel, delayed
import time
import os

def square(x):
    """Simple function to simulate computation."""
    time.sleep(0.2)
    return x * x

def main():
    print("Testing joblib parallel execution...\n")
    print(f"Detected CPU cores: {os.cpu_count()}")

    try:
        # Run a small parallel computation
        results = Parallel(n_jobs=-1)(
            delayed(square)(i) for i in range(10)
        )

        print("\nParallel job finished successfully.")
        print(f"Results: {results}")

        # Verify that all results are correct
        if results == [i * i for i in range(10)]:
            print("\n✅ Joblib parallel execution works correctly!")
        else:
            print("\n⚠️ Joblib ran, but results are incorrect.")
    except Exception as e:
        print("\n❌ Joblib parallel execution failed.")
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
