"""Autonomous explainer builder: one compact planning call, everything else is code.

The model chooses the story (cuts, beats, labels). Deterministic code anchors every cue to a
spoken word, picks icons/B-roll/memes/music/SFX from the local library, applies the motion
and sound policy, and enforces length. This keeps a full build to ~1-2 model requests.
"""
