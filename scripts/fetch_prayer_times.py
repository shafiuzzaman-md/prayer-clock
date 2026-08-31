#!/usr/bin/env python3
"""Fetch today's prayer times from arrahman.azurewebsites.net and write prayer-times.json.

Exits non-zero on any fetch/parse failure so the workflow never publishes a
broken or partial file — the clock page then falls back to its CORS proxies.
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

SOURCE_URL = "https://arrahman.azurewebsites.net/"
MOSQUE_TZ = ZoneInfo("America/Los_Angeles")
PRAYERS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", re.I)


class PrayerPageParser(HTMLParser):
    """Pulls the Athan/Iqama rows out of table.prayer-times-table and the
    sunrise/sunset times out of the span[title=...] elements."""

    def __init__(self):
        super().__init__()
        self.athan = {}
        self.iqama = {}
        self.sun = {}  # "Sunrise" / "Sunset" -> time string
        self._row_label = None       # "athan" / "iqama" once known for current row
        self._cell_prayer = None     # data-prayer of the <td> we're inside
        self._cell_text = []
        self._in_label_cell = False
        self._label_text = []
        self._sun_title = None       # title attr of the span we're inside
        self._sun_text = []
        self._sun_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self._row_label = None
        elif tag == "td":
            if attrs.get("data-prayer") in PRAYERS:
                self._cell_prayer = attrs["data-prayer"]
                self._cell_text = []
            else:
                self._in_label_cell = True
                self._label_text = []
        elif tag == "span":
            if self._sun_title:
                self._sun_depth += 1
            elif attrs.get("title") in ("Sunrise", "Sunset"):
                self._sun_title = attrs["title"]
                self._sun_text = []
                self._sun_depth = 1

    def handle_endtag(self, tag):
        if tag == "td":
            if self._cell_prayer:
                text = "".join(self._cell_text).strip()
                if self._row_label == "athan":
                    self.athan[self._cell_prayer.lower()] = text
                elif self._row_label == "iqama":
                    self.iqama[self._cell_prayer.lower()] = text
                self._cell_prayer = None
            elif self._in_label_cell:
                label = "".join(self._label_text).strip().lower()
                if "athan" in label:
                    self._row_label = "athan"
                elif "iqama" in label:
                    self._row_label = "iqama"
                self._in_label_cell = False
        elif tag == "span" and self._sun_title:
            self._sun_depth -= 1
            if self._sun_depth == 0:
                m = TIME_RE.search("".join(self._sun_text))
                if m:
                    self.sun[self._sun_title] = m.group(1).upper()
                self._sun_title = None

    def handle_data(self, data):
        if self._cell_prayer:
            self._cell_text.append(data)
        elif self._in_label_cell:
            self._label_text.append(data)
        if self._sun_title:
            self._sun_text.append(data)


def main():
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "prayer-clock-fetcher"})
    with urllib.request.urlopen(req, timeout=30) as res:
        html = res.read().decode("utf-8", errors="replace")

    parser = PrayerPageParser()
    parser.feed(html)

    for name in (p.lower() for p in PRAYERS):
        t = parser.athan.get(name, "")
        if not TIME_RE.fullmatch(t):
            sys.exit(f"Bad or missing athan time for {name}: {t!r}")

    # The source page sometimes lists Fajr iqama as PM; it is always AM.
    if parser.iqama.get("fajr"):
        parser.iqama["fajr"] = re.sub(r"PM$", "AM", parser.iqama["fajr"], flags=re.I)

    now = datetime.now(MOSQUE_TZ)
    out = {
        "date": now.strftime("%Y-%m-%d"),
        "athan": parser.athan,
        "iqama": parser.iqama,
        "sunrise": parser.sun.get("Sunrise"),
        "sunset": parser.sun.get("Sunset"),
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    path = sys.argv[1] if len(sys.argv) > 1 else "prayer-times.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"Wrote {path}: {json.dumps(out)}")


if __name__ == "__main__":
    main()
