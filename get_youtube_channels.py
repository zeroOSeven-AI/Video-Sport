
import os
import json
import requests

API_KEY = os.environ.get("YOUTUBE_API_KEY")

if not API_KEY:
    raise SystemExit("Nedostaje YOUTUBE_API_KEY!")

BASE_URL = "https://www.googleapis.com/youtube/v3"

CHANNELS = {
    "Formula 1": "@formula1",
    "Premier League": "@premierleague",
    "Bundesliga": "@bundesliga",
    "LaLiga": "@laliga",
    "Serie A": "@seriea",
    "Ligue 1": "@ligue1",
    "Liga Portugal": "@sportdigital_primeiraliga",
    "Eredivisie": "@sportdigital_eredivisie",
    "HNL": "@max-sport",
    "UEFA": "@uefa"
}

def get_channel_id(handle):
    response = requests.get(
        f"{BASE_URL}/channels",
        params={
            "part": "id,snippet",
            "forHandle": handle,
            "key": API_KEY
        },
        timeout=30
    )
    response.raise_for_status()

    items = response.json().get("items", [])

    if not items:
        return None

    channel = items[0]
    return {
        "id": channel["id"],
        "title": channel["snippet"]["title"]
    }


def get_channel_from_video(video_id):
    response = requests.get(
        f"{BASE_URL}/videos",
        params={
            "part": "snippet",
            "id": video_id,
            "key": API_KEY
        },
        timeout=30
    )
    response.raise_for_status()

    items = response.json().get("items", [])

    if not items:
        return None

    snippet = items[0]["snippet"]

    return {
        "id": snippet["channelId"],
        "title": snippet["channelTitle"]
    }


found = {}

print("\n=== YOUTUBE KANALI ===\n")

for name, handle in CHANNELS.items():
    try:
        result = get_channel_id(handle)
        found[name] = result

        if result:
            print(f"[OK] {name}: {result['title']}")
            print(f"     ID: {result['id']}")
        else:
            print(f"[NIJE PRONAĐEN] {name}: {handle}")

    except Exception as error:
        print(f"[GREŠKA] {name}: {error}")


print("\n=== SÜPER LIG VIDEO ===\n")

try:
    result = get_channel_from_video("L9FZyM2bvhY")
    found["Süper Lig"] = result

    if result:
        print(f"[OK] Kanal: {result['title']}")
        print(f"     ID: {result['id']}")
    else:
        print("[NIJE PRONAĐEN] Video ili kanal")

except Exception as error:
    print("[GREŠKA]", error)


football_names = {
    "Premier League": "Premier League Official",
    "Bundesliga": "Bundesliga Official",
    "LaLiga": "LaLiga Official",
    "Serie A": "Serie A Official",
    "Ligue 1": "Ligue 1 Official",
    "Liga Portugal": "Liga Portugal",
    "Eredivisie": "Eredivisie",
    "Süper Lig": "Süper Lig",
    "HNL": "SuperSport HNL",
    "UEFA": "UEFA Official"
}

sources = []

for league, channel_name in football_names.items():
    result = found.get(league)

    if result:
        sources.append({
            "name": channel_name,
            "league_name": league,
            "channel_id": result["id"],
            "enabled": True
        })

football_config = {
    "youtube_sources": sources
}

f1_config = {
    "youtube_sources": [
        {
            "name": "Formula 1 Official",
            "channel_id": found["Formula 1"]["id"],
            "enabled": True
        }
    ]
} if found.get("Formula 1") else {"youtube_sources": []}

print("\n=== FOOTBALL CONFIG ===\n")
print(json.dumps(football_config, indent=2, ensure_ascii=False))

print("\n=== F1 CONFIG ===\n")
print(json.dumps(f1_config, indent=2, ensure_ascii=False))

with open("youtube_channels_found.json", "w", encoding="utf-8") as file:
    json.dump(
        {
            "football": football_config,
            "f1": f1_config
        },
        file,
        indent=2,
        ensure_ascii=False
    )

print("\nSpremljeno u youtube_channels_found.json")
