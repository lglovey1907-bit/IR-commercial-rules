"""
IR Commercial Rules Scraper
Scrapes Indian Railways commercial circulars from official sources,
classifies them by subject, updates the local JSON database,
and sends a Telegram alert when new circulars are found.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import hashlib
from datetime import datetime

SOURCES = [
    {
        "name": "Indian Railway Rules - Coaching",
        "url": "https://www.indianrailwayrules.com/coaching/",
        "type": "list"
    },
    {
        "name": "Indian Railway Rules - Circulars",
        "url": "https://www.indianrailwayrules.com/circulars/",
        "type": "list"
    },
    {
        "name": "Indian Railway Rules - RBE Orders",
        "url": "https://www.indianrailwayrules.com/railway-board-orders/",
        "type": "list"
    },
]

SUBJECT_MAP = {
    "PRS / Reservation": [
        "prs", "reservation", "berth", "reserved ticket", "e-ticket",
        "internet booking", "tatkal", "premium tatkal", "quota", "waitlist",
        "confirm berth", "passenger reservation"
    ],
    "UTS / Unreserved": [
        "uts", "unreserved", "platform ticket", "season ticket",
        "monthly ticket", "quarterly ticket", "mst", "qst"
    ],
    "ATVM / Vending": [
        "atvm", "vending machine", "ticket vending", "jan sadharan"
    ],
    "Ticket Checking": [
        "ticket checking", " tc ", "tte", "travelling ticket",
        "ticket examiner", "without ticket", "excess fare", "efd"
    ],
    "Catering": [
        "catering", "pantry car", "rail neer", "food plaza",
        "jan ahar", "jan ahaar", "food", "meals"
    ],
    "Concessions": [
        "concession", "free pass", "pto", "privilege ticket",
        "pass", "disability", "handicapped", "senior citizen"
    ],
    "Refund & Cancellation": [
        "refund", "cancellation", "cancel", "tdr", "ticket deposit receipt"
    ],
    "Fare & Tariff": [
        "fare", "tariff", "fare revision", "basic fare", "freight charge",
        "supplementary charge", "superfast", "reservation fee"
    ],
    "Goods & Parcel": [
        "luggage", "parcel", "freight", "goods", "cargo",
        "consignment", "booking of luggage", "unaccompanied"
    ],
    "Coaching Operations": [
        "coaching", "train composition", "rakelink", "lhb", "icf",
        "ac coach", "sleeper", "pantry"
    ],
    "Lost Property": [
        "lost property", "unclaimed", "found property", "missing luggage"
    ],
    "RTI / Complaints": [
        "rti", "complaint", "grievance", "public grievance", "pgrams"
    ],
}

SUBJECT_EMOJI = {
    "PRS / Reservation": "🎫",
    "UTS / Unreserved": "🎟",
    "ATVM / Vending": "🏧",
    "Ticket Checking": "🔍",
    "Catering": "🍱",
    "Concessions": "🤝",
    "Refund & Cancellation": "↩️",
    "Fare & Tariff": "💰",
    "Goods & Parcel": "📦",
    "Coaching Operations": "🚃",
    "Lost Property": "🔎",
    "RTI / Complaints": "📋",
    "General / Other": "📄",
}


def classify_subject(title: str) -> str:
    title_lower = title.lower()
    for subject, keywords in SUBJECT_MAP.items():
        if any(kw in title_lower for kw in keywords):
            return subject
    return "General / Other"


def make_uid(url: str, title: str) -> str:
    raw = f"{url}|{title}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def extract_cc_number(title: str) -> str:
    patterns = [
        r"CC[- ]?(\d+)[/\-](\d{2,4})",
        r"No\.?\s*(\d+)[/\-](\d{2,4})",
        r"RBE\s*No\.?\s*(\d+)[/\-](\d{2,4})",
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return ""


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def scrape_source(source: dict) -> list:
    results = []
    try:
        print(f"  Fetching {source['url']}...")
        resp = requests.get(source["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find all links
        all_links = soup.find_all("a", href=True)
        print(f"    Found {len(all_links)} links total")

        for a in all_links:
            title = a.get_text(separator=" ", strip=True)
            href = a["href"].strip()

            # Filter by length
            if len(title) < 15 or href.startswith("#"):
                continue

            # Fix relative URLs
            if href.startswith("/"):
                from urllib.parse import urlparse
                base = urlparse(source["url"])
                href = f"{base.scheme}://{base.netloc}{href}"
            elif not href.startswith("http"):
                continue

            # Look for signal words
            signals = [
                "circular", "order", "instruction", "cc-", "cc ",
                "rbe", "rule", "chapter", "policy", "notification",
                "guideline", "amendment", "board", "bulletin"
            ]
            if not any(s in title.lower() or s in href.lower() for s in signals):
                continue

            # Create record
            record = {
                "uid": make_uid(href, title),
                "title": title,
                "url": href,
                "cc_number": extract_cc_number(title),
                "subject": classify_subject(title),
                "source": source["name"],
                "fetched_on": datetime.today().strftime("%Y-%m-%d"),
                "is_new": True,
            }
            results.append(record)

    except requests.exceptions.RequestException as e:
        print(f"  ⚠️  Error fetching {source['url']}: {e}")
    except Exception as e:
        print(f"  ⚠️  Parse error: {e}")

    return results


DB_PATH = "data/circulars.json"


def load_db() -> list:
    if os.path.exists(DB_PATH):
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_db(records: list):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def update_database(new_items: list):
    existing = load_db()
    existing_uids = {item["uid"] for item in existing}

    for item in existing:
        item["is_new"] = False

    added_items = []
    for item in new_items:
        if item["uid"] not in existing_uids:
            existing.append(item)
            existing_uids.add(item["uid"])
            added_items.append(item)

    existing.sort(key=lambda x: x.get("fetched_on", ""), reverse=True)
    save_db(existing)
    return added_items


def send_telegram_alert(new_items: list):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        print("ℹ️  Telegram secrets not set — skipping alert.")
        return

    today = datetime.today().strftime("%d %b %Y")

    lines = [
        f"🚂 *IR Commercial Rules Update*",
        f"📅 {today} — *{len(new_items)} new circular(s) added*",
        "",
    ]

    for item in new_items[:10]:
        emoji = SUBJECT_EMOJI.get(item["subject"], "📄")
        cc = f" `{item['cc_number']}`" if item.get("cc_number") else ""
        title = item["title"][:80] + ("…" if len(item["title"]) > 80 else "")
        lines.append(f"{emoji} *{item['subject']}*{cc}")
        lines.append(f"  [{title}]({item['url']})")
        lines.append("")

    if len(new_items) > 10:
        lines.append(f"_…and {len(new_items) - 10} more. Visit dashboard for full list._")
        lines.append("")

    dashboard_url = os.environ.get("DASHBOARD_URL", "https://lglovey1907-bit.github.io/IR-commercial-rules")
    lines.append(f"[📊 Open Dashboard]({dashboard_url})")

    message = "\n".join(lines)

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(api_url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"✅ Telegram alert sent")
        else:
            print(f"⚠️  Telegram error {resp.status_code}")
    except Exception as e:
        print(f"⚠️  Telegram failed: {e}")


def print_stats(records: list):
    from collections import Counter
    subjects = Counter(r["subject"] for r in records)
    print("\n📊 Subject-wise count:")
    for subj, count in subjects.most_common():
        print(f"   {subj:<35} {count:>4}")


def main():
    print("=" * 70)
    print("  IR Commercial Rules Scraper")
    print(f"  Started: {datetime.today().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    all_new = []
    for source in SOURCES:
        print(f"\n🔍 Scraping: {source['name']}")
        items = scrape_source(source)
        print(f"   ✅ Found {len(items)} potential records")
        all_new.extend(items)

    print(f"\n📥 Total items to process: {len(all_new)}")

    added_items = update_database(all_new)
    all_records = load_db()

    print(f"\n✅ Added {len(added_items)} NEW records")
    print(f"📁 Total in database: {len(all_records)}")
    print_stats(all_records)

    if added_items:
        print(f"\n📲 Sending Telegram alert...")
        send_telegram_alert(added_items)
    else:
        print("\n📭 No new circulars today")

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
