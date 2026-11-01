# 5-minute demo script (Meko Track A)

**Before you start:** run `uv run python scripts/meko_seed.py --reset` (seeded history, labelled).
Open `/app`, pick the demo reel, set the creator to **Riya**, and open the **Memory** tab on the right.

| Time | Do | Say |
|---|---|---|
| 0:00–0:30 | Show the reel and the timeline (captions, 2 face zooms). | "Agencies cut reels for creators. Every edit starts from zero: Riya repeats 'yellow captions, no face zooms, cut basically' every single time." |
| 0:30–1:30 | Untick **Memory**. Edit mode: *"Make this reel ready to post in my usual style."* | The card says **Memory off**. The result has uppercase pink captions and the zooms stay. "It has no idea what 'my usual style' means." |
| 1:30–1:45 | Undo. | "Same version, same prompt." |
| 1:45–3:00 | Tick **Memory**, send the same message. | The card lists 5 recalled items with sources. The Director calls `remove_zooms` and switches to a yellow highlight. "Recall happens before the first model turn. That's the only place it can change the plan." Point at **meko_stored**: this turn teaches the next one. |
| 3:00–3:45 | Memory tab: a chat-extracted memory → **Approve for Riya**; a generic one → **Share with agency**; a noisy one → **Forget**. | "Meko extracts preferences, but a person decides what becomes canon. The agency lesson now reaches Arjun's reels too." Switch the creator to Arjun: the agency canon is there, Riya's private style is not. |
| 3:45–4:30 | Show the **Meko calls** log and the counters. | "Every line on screen comes from a real, logged Meko call: tool, datapack, agent, rows, latency." |
| 4:30–5:00 | Feature proposal slide. | "Media-anchored memories: Meko memories are text-only, but a reel editor needs 'this caption style, at this frame'." |

Fallback if the network is slow: recall degrades to a partial recall (the card shows "Partial
recall"). Say so; don't hide it.
