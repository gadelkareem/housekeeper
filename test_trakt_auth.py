#!/usr/bin/env python3
"""
Test script to verify Trakt authentication and token refresh functionality.
This script can be used to test the fixes for the daily authentication issue.
"""

import sys
import os
from datetime import datetime

# Add the current directory and lib directory to the path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.join(current_dir, 'lib'))

# Import with absolute imports to avoid relative import issues
from lib.trakt_client import TraktClient
from lib.config import config

def test_trakt_auth():
    """Test Trakt authentication and token handling"""
    print("Testing Trakt authentication...")
    
    # Check if Trakt is configured
    if not config.trakt:
        print("ERROR: Trakt configuration not found in config.yaml")
        print("Please add trakt configuration with client_id and client_secret")
        return False
    
    try:
        # Create TraktClient instance
        print("Creating Trakt client...")
        print(f"Auth file will be stored at: {os.path.join(config.root_path, '.auth.pkl')}")
        trakt_client = TraktClient()
        
        # Check if we have valid authorization
        if trakt_client.authorization:
            print("✓ Found existing authorization")
            
            # Check token expiry information
            expires_in = trakt_client.authorization.get('expires_in', 0)
            created_at = trakt_client.authorization.get('created_at')
            
            if created_at and expires_in:
                expiry_time = created_at + expires_in
                current_time = datetime.now().timestamp()
                remaining_hours = (expiry_time - current_time) / 3600
                
                print(f"✓ Token created: {datetime.fromtimestamp(created_at)}")
                print(f"✓ Token expires in: {expires_in} seconds ({expires_in/3600:.1f} hours)")
                print(f"✓ Time remaining: {remaining_hours:.1f} hours")
                
                if remaining_hours > 0:
                    print("✓ Token is still valid")
                else:
                    print("⚠ Token has expired")
            else:
                print("⚠ Token expiry information missing or incomplete")
        else:
            print("⚠ No existing authorization found")
        
        # Test getting watched movies (this will test token refresh if needed)
        print("\nTesting API call (will refresh token if needed)...")
        movies = trakt_client.watched_movies(recent_days=7)  # Get last 7 days
        print(f"✓ Successfully retrieved {len(movies)} watched movies from last 7 days")
        
        # Test getting watched series
        print("\nTesting series API call...")
        series = trakt_client.watched_series(recent_days=7)  # Get last 7 days
        print(f"✓ Successfully retrieved {len(series)} watched series from last 7 days")
        
        print("\n✓ All tests passed! Trakt authentication is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_trakt_auth()
    sys.exit(0 if success else 1)
