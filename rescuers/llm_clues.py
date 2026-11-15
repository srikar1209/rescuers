"""
LLM step: witness text -> structured clues for infer.py.

The LLM ONLY reads text. It never makes up coordinates. Places come back as words
("the Sunoco on Route 9"), then geocode() finds them on the map, and the app shows the
point so a person can confirm or drag it.

Setup:   pip install anthropic      and set ANTHROPIC_API_KEY
Use:
    from rescuers.llm_clues import extract_clues, to_model_clues
    raw = extract_clues(text, last_seen="18:30", now="21:00", description="79, gray coat")
    clues, profile = to_model_clues(raw)      # clues -> infer.clue_likelihood, profile -> simulate()
"""

import json
import anthropic

MODEL = "claude-haiku-5-5"   # fast and cheap; switch to "claude-sonnet-5-5" for messy reports

SYSTEM = """You turn reports about a missing person with dementia into structured clues for a search model.

Context:
- Last seen time: {last_seen}
- Time of this report: {now}
- Person's description: {description}

Rules:
1. Extract only what the text says. Never invent facts, places, or times.
2. Never give coordinates. Describe each place in words, exactly as the text names it
   (landmark, business, street, intersection). Add "Amherst, MA" only if no town is named.
3. Times: 24-hour HH:MM. Turn relative times ("about an hour ago") into clock times using
   the report time. If no time is given, use null.
4. Clue types:
   - sighting: someone saw a person who may be them (in person or on a camera).
   - camera_negative: camera footage was checked and the person was NOT seen. Give the
     time window that was checked.
   - area_searched: an area was searched and the person was NOT found. Estimate the radius
     in meters from the text (a house and yard ~ 50, a park ~ 150, a neighborhood ~ 400).
   - direction: which way the person was heading when last seen (N, NE, E, SE, S, SW, W, NW).
   - goal: a place they may try to reach (old home, former job, church, a relative's house).
5. reliability:
   - high: clear, close, recent sighting that matches the description
   - medium: normal sighting with some doubt
   - low: unsure words ("I think", "maybe"), far away, dark, or the description does not match
6. If clothing or looks clearly differ from the description, say so in notes and use low.
7. If two reports describe the same event, return it once.
8. If nothing in the text is a usable clue, return an empty list.
9. For every clue, copy the short part of the text it came from into "quote".
Always answer by calling the record_clues tool."""

TOOL = {
    "name": "record_clues",
    "description": "Record every clue found in the report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "clues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string",
                                 "enum": ["sighting", "camera_negative", "area_searched",
                                          "direction", "goal"]},
                        "place": {"type": ["string", "null"],
                                  "description": "Place in words, never coordinates"},
                        "time": {"type": ["string", "null"], "description": "HH:MM, 24-hour"},
                        "window_start": {"type": ["string", "null"]},
                        "window_end": {"type": ["string", "null"]},
                        "radius_m": {"type": ["number", "null"]},
                        "direction": {"type": ["string", "null"],
                                      "enum": ["N", "NE", "E", "SE", "S", "SW", "W", "NW", None]},
                        "reliability": {"type": "string", "enum": ["high", "medium", "low"]},
                        "quote": {"type": "string"},
                        "notes": {"type": ["string", "null"]},
                    },
                    "required": ["type", "reliability", "quote"],
                },
            }
        },
        "required": ["clues"],
    },
}

RELIABILITY = {"high": 0.9, "medium": 0.7, "low": 0.4}     # ASSUMPTION, used by sighting clues
HEADING = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


def extract_clues(text, last_seen, now, description="unknown", client=None):
    """Witness text -> list of raw clue dicts (places still in words)."""
    client = client or anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL, max_tokens=1500,
        system=SYSTEM.format(last_seen=last_seen, now=now, description=description),
        tools=[TOOL], tool_choice={"type": "tool", "name": "record_clues"},
        messages=[{"role": "user", "content": text}],
    )
    for block in msg.content:
        if block.type == "tool_use":
            return block.input.get("clues", [])
    return []


# ---------------- places in words -> lat/lon ----------------
_NAMES = None


def geocode(place, features_path="data/amherst_full_features.geojson"):
    """
    Find a place name on our OSM map (exact, then partial match on the 'name' field).
    Returns (lat, lon) or None. The app should ALWAYS show the point for a human to confirm,
    and let them click the map when this returns None.
    """
    global _NAMES
    if not place:
        return None
    if _NAMES is None:
        import geopandas as gpd
        f = gpd.read_file(features_path)
        f = f[f["name"].notna()] if "name" in f.columns else f.iloc[0:0]
        pts = f.geometry.representative_point()
        _NAMES = [(str(n).lower(), p.y, p.x) for n, p in zip(f["name"], pts)]
    q = place.lower().replace(", amherst, ma", "").strip()
    for n, lat, lon in _NAMES:
        if n == q:
            return lat, lon
    hits = [(len(n), lat, lon) for n, lat, lon in _NAMES if q in n or (n in q and len(n) > 4)]
    if hits:
        _, lat, lon = max(hits)      # longest matching name = most specific
        return lat, lon
    return None


def to_model_clues(raw, geocoder=geocode):
    """
    Raw LLM clues -> (clues for infer.clue_likelihood, profile for sim.simulate).
    Clues whose place could not be found get "needs_location": True so the app asks the user.
    """
    clues, profile = [], {"heading": None, "goal": None}
    for i, c in enumerate(raw, 1):
        loc = geocoder(c.get("place"))
        base = {"id": i, "quote": c.get("quote"), "notes": c.get("notes"),
                "reliability": RELIABILITY[c.get("reliability", "medium")],
                "place_text": c.get("place"), "needs_location": loc is None}
        if loc:
            base["lat"], base["lon"] = loc
        t = c["type"]
        if t == "sighting":
            clues.append({**base, "type": "sighting", "time": c.get("time")})
        elif t == "camera_negative":
            clues.append({**base, "type": "camera_negative",
                          "window": [c.get("window_start"), c.get("window_end")]})
        elif t == "area_searched":
            clues.append({**base, "type": "area_searched", "radius_m": c.get("radius_m") or 150,
                          "time": c.get("time")})
        elif t == "direction" and c.get("direction"):
            profile["heading"] = HEADING[c["direction"]]
        elif t == "goal":
            profile["goal"] = {"place_text": c.get("place"), "lat": base.get("lat"),
                               "lon": base.get("lon"), "needs_location": loc is None}
    return clues, profile


if __name__ == "__main__":
    text = ("Hi, I work at the gas station on Route 9. Around quarter to seven I think I saw an "
            "older man in a gray coat walking west past the pumps. Also, the bank said their ATM "
            "camera on N Pleasant St shows nobody between 6:30 and 7:30. Police already checked "
            "the West Cemetery, no sign of him. His daughter says he used to work at the old mill.")
    raw = extract_clues(text, last_seen="18:30", now="21:00", description="79, gray coat")
    print(json.dumps(raw, indent=2))
    clues, profile = to_model_clues(raw)
    print(json.dumps({"clues": clues, "profile": profile}, indent=2, default=str))
