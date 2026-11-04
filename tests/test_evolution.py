#!/usr/bin/env python3

"""Test script to verify evolution tracking functionality."""

import sys
import os

# Add the project root to path so we can import modules directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from malo.core.evolution import get_current_traits, track_mode_usage, save_tracking_data

def main():
    # Simulate switching modes
    track_mode_usage("pro")
    track_mode_usage("malo") 
    track_mode_usage("pro")
    
    traits = get_current_traits()
    print(traits)
    
    # Save to disk
    save_tracking_data()

if __name__ == "__main__":
    main()