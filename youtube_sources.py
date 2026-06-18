import os
import json
import requests
from datetime import datetime

# Configuration
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# Dictionary of sources with their clean filenames and YouTube Channel IDs
SOURCES = {
    "formula_1": {"name": "Formula 1", "id": "UCB_qrNyFAFJGdxK69F8S3FQ"},
    "the_race": {"name": "The Race", "id": "UC9suvGlsc2EFr7SIsgWInXQ"},
    "driver61": {"name": "Driver61", "id": "UCJpChgSOTKT9wdxw5fJ53gQ"},
    "p1_matt_tommy": {"name": "P1 with Matt & Tommy", "id": "UCRXn6VOfHAt8zNf8D3ndFcw"},
    "autosport": {"name": "Autosport", "id": "UCZ0SstM3sS_vD_f6v798pDw"},
    "sky_sports_f1": {"name": "Sky Sports F1", "id": "UCgN40g9_RE93nNfX-vS_uRw"}
}

def fetch_and_save_channel(slug, info):
    print(f"Processing source: {info['name']}")
    # Fetching the last 10 videos from the channel
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={info['id']}&part=id,snippet&order=date&maxResults=10&type=video"
    
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Error fetching {info['name']}: {response.text}")
            return
            
        data = response.json()
        video_ids = []
        video_details = []
        
        for item in data.get("items", []):
            v_id = item["id"]["videoId"]
            video_ids.append(v_id)
            video_details.append({
                "video_id": v_id,
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
                "thumbnail": item["snippet"]["thumbnails"]["high"]["url"]
            })
            
        # Creating a custom playlist embed URL using the video IDs separated by commas
        ids_csv = ",".join(video_ids)
        embed_url = f"https://www.youtube.com/embed/{video_ids[0]}?playlist={ids_csv}" if video_ids else ""
        
        # Structure for this specific channel's JSON
        output_data = {
            "source_name": info["name"],
            "channel_id": info["id"],
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "video_ids": video_ids,
            "playlist_embed_url": embed_url,
            "videos": video_details
        }
        
        # Save to its own separate JSON file
        filename = f"{slug}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)
        print(f"Successfully saved {filename}")
        
    except Exception as e:
        print(f"Exception while processing {info['name']}: {str(e)}")

def main():
    if not YOUTUBE_API_KEY:
        print("Missing YOUTUBE_API_KEY environment variable.")
        return

    # Loop through each source and create its independent JSON file
    for slug, info in SOURCES.items():
        fetch_and_save_channel(slug, info)

if __name__ == "__main__":
    main()
