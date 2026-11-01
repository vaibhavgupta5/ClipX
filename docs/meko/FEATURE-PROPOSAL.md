# Meko feature proposal: media-anchored memories, with cross-datapack promotion

Team Fixem · ClipZ · hackCBS 9.0. Grounded in what we hit while building (see `fixem-build`).

## 1. The friction
- **Memories are text only.** A creator's style is visual: "captions like in my 12 March reel",
  "this zoom was too much". Today we flatten that into prose ("yellow #FFD400, ~96 px"), lose the
  example, and the model can only approximate it. `artifact_put` stores files, but nothing links a
  memory to an artifact, let alone to a time range inside it.
- **Promotion stays inside one datapack.** An agency lesson found in `fixem-creator-riya` cannot be
  promoted into `fixem-agency`. Workaround: `memory_add` a copy into the agency pack, then
  `memory_promote` it. The link to the original and its provenance are lost.
- **Extraction has no gate.** One-off requests ("restyle the captions…") were stored as durable
  preferences, so a human has to clean them up.

## 2. The feature, in Meko's terms
**Anchored memories:** a memory may carry `anchors`, each pointing at an artifact (by
`content_hash`) and optionally a time range or frame. Recall returns the anchors together with the
text. Promotion keeps the anchors, and **promotion can target another datapack** the caller
maintains, keeping a `promoted_from` link.

## 3. Interface
```json
// memory_add (new optional parameter)
{"text": "Riya's caption look", "datapack_id": "dp-riya", "agent_id": "clipz:curator",
 "conversation_id": "c1",
 "anchors": [{"content_hash": "sha256:9f…", "start_ms": 12000, "end_ms": 14500,
              "kind": "example"}]}
// → {"results": [{"id": "m1", "event": "ADD", "anchors": [{"content_hash": "sha256:9f…",
//      "start_ms": 12000, "end_ms": 14500, "thumb_url": "https://…/m1-0.jpg"}]}]}

// memory_promote (new optional target_datapack_id)
{"memory_ids": ["m1"], "datapack_id": "dp-riya", "target_datapack_id": "dp-agency",
 "conversation_id": "c1"}
// → {"inserted_ids": ["m7"], "promoted_from": {"m7": {"datapack_id": "dp-riya", "memory_id": "m1"}}}
```
Plus `extract: "preferences_only"` on `conversation_add_message`, so extraction skips one-off requests.

## 4. Scenario, before and after
- **Before:** the editor types "make captions like the March reel". The agent recalls "yellow,
  ~96 px", guesses the rest, and the creator corrects it again.
- **After:** recall returns the memory **plus the 2.5 s clip and thumbnail** of the March reel. A
  vision-capable agent matches the actual look. The approved lesson is promoted into the agency
  pack with provenance, and every editor sees where it came from.

## 5. Why it's new
Context layers today (mem0-style memory, RAG over documents) treat memory as text and knowledge as
documents. None ties a durable, promotable memory to a **moment inside a media file**, and none
promotes across scopes with provenance. For video, design and audio agents, the example *is* the
memory.

## 6. Risks and limits
- **Privacy:** anchors point at content hashes the caller already stored with `artifact_put`, in
  the same datapack, under the same grants. Thumbnails inherit the datapack's access rules. No
  cross-tenant hashes.
- **Cost:** anchors are metadata (hash + range). Thumbnails are generated lazily, capped per
  memory (e.g. 3), and stored once per hash.
- **Abuse:** cross-datapack promotion requires maintainer role on **both** datapacks; every
  promotion is recorded in both traces; one-way stays one-way.
- **Prompt injection via media:** anchored media is returned as data, labelled `kind: example`;
  agents must treat OCR/ASR from it as untrusted, exactly like transcripts today.
