#!/usr/bin/env python3
"""Build a YouTube Music playlist from a text file of songs.

Usage:
    python build_playlist.py "Playlist Name" songs.txt

Each non-empty line in the song file is one search query, e.g.:
    Townes Van Zandt - Pancho and Lefty
Lines that are empty or start with '#' are ignored.

Authentication
--------------
Browser auth is the default and the only reliable method right now: Google
broke third-party OAuth for YouTube Music in late 2024, so `ytmusicapi oauth`
tokens fail every API call with "HTTP 400: Request contains an invalid
argument" (see https://github.com/sigma67/ytmusicapi/issues/676 and
https://github.com/yt-dlp/yt-dlp/issues/11462). Browser auth uses your logged-in
session cookies instead and works.

To set up browser auth:
  1. Open https://music.youtube.com while logged in.
  2. Open dev tools -> Network, filter for a POST request to /youtubei/v1/
     (e.g. /browse), right-click -> Copy -> Copy Request Headers.
  3. Paste those into raw_headers.txt next to this script.
This script regenerates browser.json from raw_headers.txt automatically when
raw_headers.txt is newer (or browser.json is missing).

NOTE: browser.json and raw_headers.txt contain your live Google session
cookies. Treat them like passwords: never commit or share them. Session cookies
expire after ~1-2 days, so you'll re-copy headers periodically.

OAuth (currently broken, kept as a fallback): pass --auth oauth.json. Client
id/secret are read from env (YTM_CLIENT_ID / YTM_CLIENT_SECRET) or from the
files under ~/.local/share/oauth/.
"""

import argparse
import os
import sys
import time

from ytmusicapi import YTMusic, setup

try:
    from ytmusicapi import OAuthCredentials
except ImportError:  # older versions
    OAuthCredentials = None

HERE = os.path.dirname(os.path.abspath(__file__))
BROWSER_JSON = os.path.join(HERE, "browser.json")
RAW_HEADERS = os.path.join(HERE, "raw_headers.txt")
OAUTH_DIR = os.path.expanduser("~/.local/share/oauth")


def regenerate_browser_json_if_needed():
    """Build browser.json from raw_headers.txt when it's stale or missing.

    The raw headers copied from the browser include the HTTP request line and a
    trailing blank line; ytmusicapi's parser turns those into a bogus header
    that the server rejects with an empty response. We strip everything that
    isn't a real "Key: Value" header line before handing it over.
    """
    if not os.path.exists(RAW_HEADERS):
        return
    fresh = os.path.exists(BROWSER_JSON) and (
        os.path.getmtime(BROWSER_JSON) >= os.path.getmtime(RAW_HEADERS)
    )
    if fresh:
        return

    lines = []
    with open(RAW_HEADERS, encoding="utf-8") as f:
        for ln in f:
            s = ln.rstrip("\n")
            if s.strip() and ": " in s:  # skip request line / pseudo-headers / blanks
                lines.append(s)
    if not lines:
        return
    setup(filepath=BROWSER_JSON, headers_raw="\n".join(lines))
    print(f"Regenerated {os.path.basename(BROWSER_JSON)} from raw_headers.txt")


def load_oauth(auth_file):
    """Load YTMusic from an oauth token, supplying client id/secret it needs."""
    if OAuthCredentials is None:
        sys.exit("This ytmusicapi version can't supply oauth_credentials; "
                 "upgrade or use browser auth.")

    cid = os.environ.get("YTM_CLIENT_ID")
    csecret = os.environ.get("YTM_CLIENT_SECRET")
    if not (cid and csecret):
        try:
            cid = open(os.path.join(OAUTH_DIR, "credential.txt")).read().strip()
            csecret = open(os.path.join(OAUTH_DIR, "secret.txt")).read().strip()
        except OSError:
            pass
    if not (cid and csecret):
        sys.exit("OAuth needs client credentials. Set YTM_CLIENT_ID and "
                 "YTM_CLIENT_SECRET, or place credential.txt/secret.txt in "
                 f"{OAUTH_DIR}, or (recommended) use browser auth.")

    print("WARNING: Google broke third-party OAuth for YT Music; API calls will "
          "likely fail with HTTP 400. Use browser auth if this errors.",
          file=sys.stderr)
    return YTMusic(auth_file, oauth_credentials=OAuthCredentials(
        client_id=cid, client_secret=csecret))


def load_ytmusic(explicit_auth):
    """Resolve an auth method and return a ready YTMusic client.

    Order: explicit --auth, else browser.json (auto-built from raw_headers.txt).
    """
    if explicit_auth:
        if not os.path.exists(explicit_auth):
            sys.exit(f"Auth file not found: {explicit_auth}")
        if "oauth" in os.path.basename(explicit_auth).lower():
            return load_oauth(explicit_auth)
        return YTMusic(explicit_auth)

    regenerate_browser_json_if_needed()
    if os.path.exists(BROWSER_JSON):
        return YTMusic(BROWSER_JSON)

    sys.exit(
        "No usable auth found.\n"
        f"  - Put your copied request headers in {RAW_HEADERS} (recommended), or\n"
        "  - pass --auth oauth.json (note: Google's OAuth break may make it fail)."
    )


def read_queries(path):
    if not os.path.exists(path):
        sys.exit(f"Song file not found: {path}")
    with open(path, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def resolve_one(yt, query):
    """Return (videoId, title) for a query, or (None, None) if not found."""
    for filt in ("songs", "videos"):
        results = yt.search(query, filter=filt, limit=1)
        if results:
            return results[0]["videoId"], results[0].get("title", "?")
    return None, None


def main():
    p = argparse.ArgumentParser(description="Build a YT Music playlist from a text file.")
    p.add_argument("name", help="Playlist name")
    p.add_argument("file", help="Text file, one song per line")
    p.add_argument("--auth", default=None,
                   help="Auth file. Default: auto (browser.json, built from "
                        "raw_headers.txt). Pass oauth.json to try OAuth.")
    p.add_argument("--privacy", default="PRIVATE",
                   choices=["PRIVATE", "PUBLIC", "UNLISTED"],
                   help="Playlist privacy (default: PRIVATE)")
    p.add_argument("--description", default="Created with ytmusicapi",
                   help="Playlist description")
    p.add_argument("--sleep", type=float, default=0.3,
                   help="Delay between searches in seconds (default: 0.3)")
    args = p.parse_args()

    queries = read_queries(args.file)
    if not queries:
        sys.exit("No songs found in file.")

    yt = load_ytmusic(args.auth)

    print(f"Resolving {len(queries)} songs from '{args.file}'...")
    video_ids = []
    not_found = []
    for i, q in enumerate(queries, 1):
        try:
            vid, title = resolve_one(yt, q)
        except Exception as e:  # network / transient: report and continue
            print(f"  [{i}/{len(queries)}] ERROR '{q}': {e}")
            not_found.append(q)
            continue

        if vid:
            video_ids.append(vid)
            print(f"  [{i}/{len(queries)}] OK   {q}  ->  {title}")
        else:
            print(f"  [{i}/{len(queries)}] MISS {q}")
            not_found.append(q)
        time.sleep(args.sleep)

    if not video_ids:
        sys.exit("Nothing resolved; not creating an empty playlist.")

    print(f"\nCreating playlist '{args.name}' with {len(video_ids)} tracks...")
    playlist_id = yt.create_playlist(
        title=args.name,
        description=args.description,
        privacy_status=args.privacy,
        video_ids=video_ids,
    )
    print(f"Done. Playlist ID: {playlist_id}")
    print(f"URL: https://music.youtube.com/playlist?list={playlist_id}")

    if not_found:
        print(f"\n{len(not_found)} not found:")
        for q in not_found:
            print(f"  - {q}")


if __name__ == "__main__":
    main()
