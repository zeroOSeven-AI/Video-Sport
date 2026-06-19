import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ======================================================
# CONFIG
# ======================================================

OUTPUT_FOLDER = "YouTube/F1"
DELAY_SECONDS = 1

# 👉 GitHub / local icons (ti ubacuješ PNG)
ICON_BASE = "Logo/"

# ======================================================
# SOURCES
# ======================================================

SOURCES = {
    "formula_1": {
        "name": "Formula 1",
        "id": "UCB_qr75-ydFVKSF9Dmo6izg",
        "icon": "f1.png"
    },
    "sky_sports_f1": {
        "name": "Sky Sports F1",
        "id": "UC3kxJQ9RfaS5CKeYbbFMi4Q",
        "icon": "sky.png"
    },
    "the_race": {
        "name": "The Race",
        "id": "UCaTxfj0BzL-MaCy-YUqPRoQ",
        "icon": "race.png"
    },
    "driver61": {
        "name": "Driver61",
        "id": "UCtbLA0YM6EpwUQhFUyPQU9Q",
        "icon": "driver61.png"
    },
    "autosport": {
        "name": "Autosport",
        "id": "UCxuksozHJD_f1w9nVa6UhAw",
        "icon": "autosport.png"
    },
    "p1_matt_tommy": {
        "name": "P1 with Matt & Tommy",
        "id": "UCD5jAyCSDRR5yTgswfDbK8w",
        "icon": "p1.png"
    }
}

# ======================================================
# PRIORITY SYSTEM
# ======================================================

CHANNEL_PRIORITY = {
    "formula_1": 100,
    "sky_sports_f1": 95,
    "the_race": 80,
    "driver61": 70,
    "autosport": 60,
    "p1_matt_tommy": 55
}

CATEGORY_BOOST = {
    "highlights": 50,
    "race": 40,
    "qualifying": 35,
    "onboard": 25,
    "interview": 20
}

FILTERS = {
    "highlights": ["highlights", "best moments"],
    "onboard": ["onboard", "on board"],
    "race": ["grand prix", "race", "gp"],
    "qualifying": ["qualifying", "qualy", "q1", "q2", "q3"],
    "interview": ["interview", "reaction"]
}

# ======================================================
# HELPERS
# ======================================================

def parse_time(date_str):
    try:
        return int(datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp())
    except:
        return 0


def classify(title):
    t = title.lower()
    tags = []
    for k, words in FILTERS.items():
        if any(w in t for w in words):
            tags.append(k)
    return tags


def calculate_priority(video, source_key):
    title = video["title"].lower()

    base = CHANNEL_PRIORITY.get(source_key, 10)

    boost = 0
    for tag in video["tags"]:
        boost = max(boost, CATEGORY_BOOST.get(tag, 0))

    # recency boost
    age_boost = 0
    if video["published_at_ts"]:
        hours = (time.time() - video["published_at_ts"]) / 3600
        if hours < 6:
            age_boost = 30
        elif hours < 24:
            age_boost = 15
        elif hours < 72:
            age_boost = 5

    return base + boost + age_boost


# ======================================================
# FETCH CHANNEL
# ======================================================

def fetch_channel(slug, info):
    print(f"Fetching {info['name']}")

    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={info['id']}"

    r = requests.get(url, timeout=10)
    r.raise_for_status()

    root = ET.fromstring(r.content)

    videos = []
    entries = root.findall("{http://www.w3.org/2005/Atom}entry")[:10]

    for e in entries:
        vid = e.find("{http://www.youtube.com/xml/schemas/2015}videoId")
        title = e.find("{http://www.w3.org/2005/Atom}title")
        published = e.find("{http://www.w3.org/2005/Atom}published")

        if vid is None:
            continue

        title_text = title.text if title is not None else ""
        published_text = published.text if published is not None else ""

        video = {
            "video_id": vid.text,
            "title": title_text,
            "published_at": published_text,
            "published_at_ts": parse_time(published_text),
            "thumbnail": f"https://i.ytimg.com/vi/{vid.text}/hqdefault.jpg",
            "link": f"https://www.youtube.com/watch?v={vid.text}",
            "channel": info["name"],
            "source_key": slug,
            "icon": ICON_BASE + info["icon"],
            "tags": classify(title_text)
        }

        video["priority"] = calculate_priority(video, slug)

        videos.append(video)

    return videos


# ======================================================
# MAIN
# ======================================================

def main():

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    all_videos = []

    for i, (slug, info) in enumerate(SOURCES.items()):

        try:
            videos = fetch_channel(slug, info)
            all_videos.extend(videos)

        except Exception as e:
            print(f"ERROR {slug}: {e}")

        if i < len(SOURCES) - 1:
            time.sleep(DELAY_SECONDS)

    # GLOBAL SORT
    all_videos.sort(key=lambda x: x["priority"], reverse=True)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_videos),
        "videos": all_videos
    }

    # SAVE MAIN FEED
    with open(f"{OUTPUT_FOLDER}/home.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    # OPTIONAL: per channel split
    per_channel = {}
    for v in all_videos:
        per_channel.setdefault(v["source_key"], []).append(v)

    for k, v in per_channel.items():
        with open(f"{OUTPUT_FOLDER}/{k}.json", "w", encoding="utf-8") as f:
            json.dump(v, f, indent=4, ensure_ascii=False)

    print("\nDONE:")
    print(f"- Total videos: {len(all_videos)}")
    print(f"- Output: {OUTPUT_FOLDER}/home.json")


if __name__ == "__main__":
    main()
