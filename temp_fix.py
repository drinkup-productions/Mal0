# Simple fix for persona tracking - just add the import and call at start of _persona method

def apply_tracking_fix():
    # Read current file content
    with open(r"C:\Users\chugs\Documents\Mal0_V1.0.2\malo\ui\kivy\app.py", "r") as f:
        content = f.read()
    
    # Find the _persona method and inject our tracking call at the beginning
    import re
    
    # Look for the _persona method definition  
    persona_pattern = r"def _persona\(self, _w, pid\):"
    
    if re.search(persona_pattern, content):
        # Insert our tracking code after the method definition but before existing logic
        fixed_content = re.sub(
            persona_pattern,
            'def _persona(self, _w, pid):\n        from ...core.evolution import track_mode_usage\n        # Track the mode switch before changing personas\n        if self.cfg.get("persona"):\n            track_mode_usage(self.cfg["persona"])',
            content,
            count=1
        )
        
        with open(r"C:\Users\chugs\Documents\Mal0_V1.0.2\malo\ui\kivy\app.py", "w") as f:
            f.write(fixed_content)
        
        return True
    
    return False

# Execute the fix
apply_tracking_fix()