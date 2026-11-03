"""
Personality evolution tracking for MalO.
This module tracks persona usage patterns to enable gradual personality development over time,
rather than just switching between fixed roles.

The system monitors:
- How often each mode is used
- Duration of time spent in each mode  
- Cross-mode interaction patterns

This information can be used later to blend personality traits or adjust behavior based on actual usage.
"""

import time
import json
from . import config, log as _log

# Track persona usage over time for evolution analysis
_PERSONA_USAGE = {}
_LAST_MODE_SWITCH = 0.0
_CURRENT_MODE = None


def track_mode_usage(mode_name):
    """Record when a persona mode is activated."""
    global _PERSONA_USAGE, _LAST_MODE_SWITCH, _CURRENT_MODE
    
    # Initialize tracking if needed
    if mode_name not in _PERSONA_USAGE:
        _PERSONA_USAGE[mode_name] = {
            "usage_count": 0,
            "total_duration": 0.0,
            "last_used": 0.0,
            "sessions": []
        }
    
    # Record session start time
    now = time.time()
    if _CURRENT_MODE != mode_name:
        # We're switching modes - record previous session duration  
        if _CURRENT_MODE and _LAST_MODE_SWITCH > 0:
            duration = now - _LAST_MODE_SWITCH
            _PERSONA_USAGE[_CURRENT_MODE]["total_duration"] += duration
            _PERSONA_USAGE[_CURRENT_MODE]["usage_count"] += 1
            
        # Start new session for the new mode  
        _PERSONA_USAGE[mode_name]["sessions"].append({
            "start": now,
            "duration": 0.0  # Will be filled in when switching again or at shutdown
        })
    
    _CURRENT_MODE = mode_name
    _LAST_MODE_SWITCH = now


def get_personality_profile():
    """Analyze usage patterns to determine current personality blend."""
    if not _PERSONA_USAGE:
        return None
        
    # Create a weighted profile based on usage frequency and duration 
    total_count = sum(trait["usage_count"] for trait in _PERSONA_USAGE.values())
    if total_count == 0:
        return None
    
    profile = {}
    for mode, trait in _PERSONA_USAGE.items():
        # Weight by normalized usage count - we don't want the most recent mode to dominate
        weight = trait["usage_count"] / total_count
        profile[mode] = weight
        
    return profile


def save_tracking_data():
    """Save usage data persistently."""
    try:
        data_file = config.paths().personas + ".evolution"
        with open(data_file, "w") as f:
            json.dump(_PERSONA_USAGE, f)
    except Exception as e:
        _log("Failed to save evolution tracking: %s" % str(e))


def load_tracking_data():
    """Load usage data from persistent storage."""
    try:
        data_file = config.paths().personas + ".evolution"
        with open(data_file, "r") as f:
            global _PERSONA_USAGE
            _PERSONA_USAGE = json.load(f)
    except Exception as e:
        # If file doesn't exist or is invalid, continue with empty tracking
        pass


def get_current_traits():
    """Return current personality traits based on usage history."""
    profile = get_personality_profile()
    if not profile:
        return None
    
    # Simple implementation - in future this could be more sophisticated
    return {
        "traits": profile,
        "timestamp": time.time(),
        "mode_count": len(profile)
    }


# Load any existing tracking data when module is initialized
load_tracking_data()


def apply_personality_blend(persona_config, traits):
    """Apply personality traits to a persona configuration (placeholder for future implementation)."""
    # This would be where we actually blend different persona characteristics
    # based on the usage profile - for now just return original config
    return persona_config


# Hook into system lifecycle if needed
def shutdown():
    """Handle cleanup and save when shutting down."""
    if _CURRENT_MODE and _LAST_MODE_SWITCH > 0:
        # Record final session duration  
        now = time.time()
        duration = now - _LAST_MODE_SWITCH
        _PERSONA_USAGE[_CURRENT_MODE]["total_duration"] += duration
        _PERSONA_USAGE[_CURRENT_MODE]["usage_count"] += 1
        
    save_tracking_data()

