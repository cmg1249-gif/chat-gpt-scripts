"""Linux cursor capture is supplied by MSS/XFixes before this hook."""
def draw_cursor(frame, monitor):
    return frame
