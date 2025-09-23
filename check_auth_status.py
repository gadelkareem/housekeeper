#!/usr/bin/env python3
"""
Script to check auth file status and path resolution.
Run this on your NAS to diagnose the auth file issue.
"""

import os
import sys
import pickle
from datetime import datetime

def check_auth_status():
    """Check the current auth file status"""
    print("TRAKT AUTH FILE STATUS CHECK")
    print("=" * 50)
    
    # Show current working directory and script location
    print(f"Current working directory: {os.getcwd()}")
    print(f"Script location: {os.path.dirname(os.path.abspath(__file__))}")
    
    # Calculate project root the same way as config.py and TraktClient
    script_dir = os.path.dirname(os.path.abspath(__file__))
    lib_dir = os.path.join(script_dir, 'lib')
    project_root_from_script = script_dir  # Since this script is in project root
    project_root_from_lib = os.path.abspath(os.path.join(lib_dir, ".."))  # Same as config.py
    
    print(f"Project root (from script): {project_root_from_script}")
    print(f"Project root (from lib): {project_root_from_lib}")
    
    # Check auth file locations
    auth_paths = [
        os.path.join(project_root_from_script, ".auth.pkl"),
        os.path.join(project_root_from_lib, ".auth.pkl"),
        os.path.join(os.getcwd(), ".auth.pkl"),
        "/volume1/Documents/scripts/housekeeping/.auth.pkl"  # Your test path
    ]
    
    print("\nChecking possible auth file locations:")
    print("-" * 50)
    
    found_auth = False
    
    for i, auth_path in enumerate(auth_paths, 1):
        print(f"{i}. {auth_path}")
        exists = os.path.exists(auth_path)
        print(f"   Exists: {exists}")
        
        if exists:
            found_auth = True
            try:
                with open(auth_path, "rb") as f:
                    auth_data = pickle.load(f)
                
                created_at = auth_data.get('created_at')
                expires_in = auth_data.get('expires_in', 0)
                access_token = auth_data.get('access_token', '')
                
                print(f"   ✓ Valid auth file found!")
                if created_at:
                    current_time = datetime.now().timestamp()
                    expiry_time = created_at + expires_in
                    remaining_hours = (expiry_time - current_time) / 3600
                    
                    print(f"   Created: {datetime.fromtimestamp(created_at)}")
                    print(f"   Expires in: {expires_in} seconds ({expires_in/3600:.1f} hours)")
                    print(f"   Remaining: {remaining_hours:.1f} hours")
                    print(f"   Token: {access_token[:10]}..." if access_token else "   Token: None")
                    
                    if remaining_hours > 0:
                        print(f"   Status: ✓ VALID")
                    else:
                        print(f"   Status: ⚠ EXPIRED")
                else:
                    print(f"   Status: ⚠ Missing timestamp")
                    
            except Exception as e:
                print(f"   ✗ Error reading file: {e}")
        
        print()
    
    if not found_auth:
        print("⚠ No auth files found in any location")
        print("\nThis explains why you're getting authentication prompts.")
        print("The auth file created during your test is not being found by the main scripts.")
    
    # Check directory permissions
    print("\nDirectory permissions:")
    print("-" * 30)
    for auth_path in auth_paths[:3]:  # Check first 3 directories
        dir_path = os.path.dirname(auth_path)
        if os.path.exists(dir_path):
            readable = os.access(dir_path, os.R_OK)
            writable = os.access(dir_path, os.W_OK)
            print(f"{dir_path}")
            print(f"  Readable: {readable}")
            print(f"  Writable: {writable}")
        else:
            print(f"{dir_path} - Does not exist")
    
    # Show current user info
    print(f"\nCurrent user: {os.getenv('USER', 'unknown')}")
    print(f"Running as root: {os.getuid() == 0 if hasattr(os, 'getuid') else 'unknown'}")
    
    return found_auth

if __name__ == "__main__":
    check_auth_status()

