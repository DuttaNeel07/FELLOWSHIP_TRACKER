"""
AI-Powered Fellowship & Internship Scraper
==========================================
"""

import argparse
import calendar
import os
import re
import json
import asyncio
import time
from pathlib import Path
from datetime import datetime, timezone, date
from urllib.parse import urlparse, urlunparse

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from groq import Groq
from scraper.discord import send_discord_notification

# ─────────────────────────── ENV SETUP ───────────────────────────
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

MONGO_URL  = os.getenv("MONGO_URL")
SERPER_KEY = os.getenv("SERPER_API_KEY")
GROQ_KEY    = os.getenv("GROQ_API_KEY")

mongo_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db           = mongo_client.fellowship_tracker
collection   = db.fellowships
discovered_collection = db.discovered_links

groq_client = Groq(api_key=GROQ_KEY)
ai_lock = asyncio.Lock()

GROQ_MODEL  = "llama-3.3-70b-versatile"

STUDENT_PROFILE = {
    "location": "Bangalore, Karnataka, India",
    "education": "B.Tech / B.E. (undergraduate) or M.Tech (postgraduate)",
    "domains": ["computer science", "software engineering", "AI/ML", "open source", "research", "hackathons", "competitive programming"],
    "year": "2025-2026 cycle",
}

MUST_HAVE_PROGRAMS = [
    "LFX Mentorship (Linux Foundation)",
    "GSoC - Google Summer of Code",
    "DWoC - Delta Winter of Code",
    "KWoC - Kharagpur Winter of Code",
    "CNCF Mentorship Program",
    "Summer of Bitcoin",
    "FOSS United Fellowship",
    "Reliance Foundation Undergraduate Scholarship",
    "Grace Hopper Celebration (GHC) Scholarship",
    "LIFT Fellowship",
    "IIT Research Internship (SURGE / SPARK / SRF)",
    "SRFP - JNCASR Summer Research Fellowship",
    "SRIP - IIT Gandhinagar Summer Research Internship",
    "MSR - Microsoft Research India Fellowship",
    # ── Hackathons ──
    "Smart India Hackathon (SIH)",
    "EthIndia",
    "HackMIT",
    "MLH Global Hack Week",
    "Hackverse NITK",
    "HackCBS",
    "Hacktoberfest",
    "ETHGlobal",
    "Devfolio hackathons",
    "HackBangalore",
    "Bangalore Hackathon Week",
    "Junction Asia Hackathon",
    # ── Competitive Programming ──
    "ICPC India Regionals",
    "Meta Hacker Cup",
    "CodeChef Starters",
    "AtCoder Beginner Contest",
    "HackerEarth Circuits",
    "Topcoder SRM",
]

# Patterns for transient/recurring contests that shouldn't be stored individually
SKIP_TRANSIENT_PATTERNS = [
    re.compile(r"codeforces\s+(round|div)", re.IGNORECASE),
    re.compile(r"leetcode\s+weekly\s+contest", re.IGNORECASE),
    re.compile(r"leetcode\s+biweekly\s+contest", re.IGNORECASE),
    re.compile(r"codechef\s+starters\s+\d", re.IGNORECASE),
    re.compile(r"atcoder\s+beginner\s+contest\s+\d", re.IGNORECASE),
    re.compile(r"atcoder\s+regular\s+contest\s+\d", re.IGNORECASE),
]

def _is_transient_contest(name: str) -> bool:
    """Return True if the opportunity is a recurring weekly/biweekly contest."""
    return any(pat.search(name) for pat in SKIP_TRANSIENT_PATTERNS)

BLACKLISTED_DOMAINS = {
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "youtube.com", "pinterest.com", "reddit.com",
    "quora.com", "medium.com", "t.co", "bit.ly",
}

def build_discovery_queries() -> list[str]:
    """Generate search queries with current month/year so results are always timely."""
    today = date.today()
    year = today.year
    cur_month = today.strftime("%B")       # e.g. "March"
    next_month = date(today.year + (1 if today.month == 12 else 0),
                      (today.month % 12) + 1, 1).strftime("%B")

    return [
        # Fellowships
        f"computer science fellowship {year} apply",
        f"AI internship for students {year}",
        f"summer research program computer science {year}",
        f"undergraduate research internship India {year}",
        f"open source mentorship program {year}",
        f"engineering fellowship for students {year}",
        "research internship Bangalore computer science",
        "remote AI fellowship students",
        # Hackathons – dynamic months
        f"upcoming hackathons Bangalore {year}",
        f"upcoming hackathons India {cur_month} {next_month} {year}",
        f"hackathon registration open India {year}",
        "student hackathon Bangalore register",
        "devfolio upcoming hackathons",
        f"unstop upcoming hackathon {year}",
        f"MLH hackathon schedule {year}",
        f"college hackathon India {year}",
        f"web3 hackathon India {year}",
        f"AI ML hackathon India {year}",
        # Competitive Programming
        f"competitive programming contest schedule {year}",
        "codeforces upcoming rounds",
        f"codechef contests {year}",
        f"ICPC regionals India {year}",
        "leetcode contest schedule",
        "hackerearth upcoming challenge",
        "atcoder upcoming contest",
    ]

DISCOVERY_DOMAINS = [
    "https://iisc.ac.in",
    "https://iiit.ac.in",
    "https://research.google",
    "https://careers.microsoft.com",
    "https://cncf.io",
    "https://linuxfoundation.org",
    "https://mlh.io",
    "https://outreachy.org",
    "https://devfolio.co",
    "https://unstop.com",
    "https://hackerearth.com",
    "https://codeforces.com",
    "https://codechef.com",
    "https://leetcode.com",
]

def ask_ai(prompt: str, max_tokens: int = 2048) -> str:
    """Call Groq with automatic retry on rate limits."""
    for attempt in range(4):
        try:
            resp = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                wait = (2 ** attempt) * 5 
                print(f"  ⏳ Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"Groq error: {err[:300]}")
                return ""
    return ""


def safe_parse_json(raw: str):
    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        match = re.search(r'(\{.*\}|\[.*\])', cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return None

async def get_existing_urls() -> set:
    """Fetch all URLs already stored in MongoDB."""
    existing = set()
    
    cursor = collection.find({}, {"apply_link": 1, "_id": 0})
    async for doc in cursor:
        if doc.get("apply_link"):
            existing.add(doc["apply_link"])
            
    cursor2 = discovered_collection.find({"is_processed": True}, {"apply_link": 1, "_id": 0})
    async for doc in cursor2:
        if doc.get("apply_link"):
            existing.add(doc["apply_link"])
            
    print(f"Found {len(existing)} already-scraped URLs in DB.")
    return existing


# ─────────────────────────── DOMAIN SCORING ──────────────────────

def get_domain_score(url: str) -> int:
    u = url.lower()
    if any(d in u for d in BLACKLISTED_DOMAINS): return 0
    if any(e in u for e in [".gov.in", ".nic.in", ".res.in"]): return 100
    if any(e in u for e in [".ac.in", ".edu.in"]): return 95
    tier2 = ["lfx.linuxfoundation.org", "summerofcode.withgoogle.com",
             "cncf.io", "summerofbitcoin.org", "fossunited.org",
             "jncasr.ac.in", "iitgn.ac.in", "ghc.anitab.org",
             "outreachy.org", "mlh.io", "anitab.org", "unstop.com",
             "devfolio.co", "hackerearth.com", "codeforces.com", "codechef.com", "leetcode.com"]
    if any(t in u for t in tier2): return 98
    if any(a in u for a in ["internshala", "naukri", "glassdoor", "indeed"]): return 30
    return 50


def is_link_allowed(url: str) -> bool:
    u = url.lower()
    if any(d in u for d in BLACKLISTED_DOMAINS): return False
    if u.endswith((".pdf", ".doc", ".docx", ".zip")): return False
    return True

def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    clean = parsed._replace(query="", fragment="")
    return urlunparse(clean).rstrip("/")

def generate_queries_with_ai() -> list[dict]:
    print("\nGemini is generating search queries...")
    programs_list = "\n".join(f"- {p}" for p in MUST_HAVE_PROGRAMS)

    prompt = f"""You are helping find tech fellowships, hackathons, and competitive programming contests for Indian CS students in Bangalore.

For each program below, generate exactly 3 Google search queries:
1. One targeting the official application page
2. One targeting 2026 or 2027 deadlines
3. One targeting eligibility for Indian students
Programs:
{programs_list}

Also suggest 15 additional relevant programs
Generate 3 queries each for the additional programs too.

Return ONLY this JSON with no extra text or markdown:
{{
  "must_have": [
    {{"name": "Program Name", "queries": ["query 1", "query 2", "query 3"], "official_domain_hint": "domain.com"}}
  ],
  "additional": [
    {{"name": "Program Name", "queries": ["query 1", "query 2"], "official_domain_hint": "domain.com"}}
  ]
}}"""

    raw = ask_ai(prompt, max_tokens=3000)
    if not raw:
        print("Gemini unavailable, using fallback queries.")
        return [{"name": p, "queries": [f"{p} 2026 official application", f"{p} deadline 2026"]}
                for p in MUST_HAVE_PROGRAMS]

    data = safe_parse_json(raw)
    if not data or not isinstance(data, dict):
        print("JSON parse failed, using fallback queries.")
        return [{"name": p, "queries": [f"{p} 2026 official application", f"{p} deadline 2026"]}
                for p in MUST_HAVE_PROGRAMS]

    combined = data.get("must_have", []) + data.get("additional", [])
    print(f"Generated queries for {len(combined)} programs.")
    return combined

async def serper_search(query: str, client: httpx.AsyncClient, tbs: str = "qdr:m3") -> list[str]:
    """Search via Serper with time-based filtering (default: past 3 months)."""
    headers = {"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"}
    payload = {"q": query, "gl": "in", "num": 20}
    if tbs:
        payload["tbs"] = tbs
    try:
        resp = await client.post(
            "https://google.serper.dev/search",
            json=payload,
            headers=headers, timeout=15,
        )
        results = resp.json().get("organic", [])
        return [
            r.get("link", "") for r in results
            if is_link_allowed(r.get("link", ""))
        ]

    except Exception as e:
        print(f"Serper error: {e}")
        return []


async def collect_links(programs: list[dict], tbs: str = "qdr:m3") -> list[tuple[int, str]]:
    seen, scored = set(), []
    async with httpx.AsyncClient() as http:
        for prog in programs:
            print(f"Searching: {prog['name']}")
            for query in prog.get("queries", []):
                for link in await serper_search(query, http, tbs=tbs):
                    link = normalize_url(link)
                    if link not in seen:
                        seen.add(link)
                        score = get_domain_score(link)
                        hint = prog.get("official_domain_hint", "")
                        if hint and hint.lower() in link.lower():
                            score = min(score + 15, 100)
                        scored.append((score, link))
                await asyncio.sleep(0.5)
    scored.sort(key=lambda x: x[0], reverse=True)
    print(f"\nCollected {len(scored)} unique links.\n")
    return scored

def deduplicate_by_domain(scored_links: list[tuple[int, str]], max_per_domain: int = 1) -> list[tuple[int, str]]:
    """
    Keep only the top N URLs per domain.
    Prevents 5 links from summerofbitcoin.org, 4 from cncf.io etc.
    """
    domain_count = {}
    deduped = []

    for score, url in scored_links:
        domain = urlparse(url).netloc.replace("www.", "")
        count = domain_count.get(domain, 0)
        if count < max_per_domain:
            deduped.append((score, url))
            domain_count[domain] = count + 1

    print(f"Deduplicated: {len(scored_links)} → {len(deduped)} links (max {max_per_domain} per domain)\n")
    return deduped


from urllib.parse import urlparse

def generate_domain_paths(domain_url):
    base = domain_url.rstrip("/")
    paths = [
        "/internships",
        "/fellowships",
        "/research",
        "/careers",
        "/opportunities",
        "/summer-internship",
        "/students",
        "/hackathons",
        "/contests",
    ]
    return [base + p for p in paths]

def generate_dynamic_queries():
    year = date.today().year
    topics = [
        "AI", "machine learning", "cybersecurity",
        "software engineering", "data science",
        "open source", "hackathons", "competitive programming",
        "blockchain", "web3", "cloud computing",
    ]

    templates = [
        "{{}} fellowship students {y}",
        "{{}} internship undergraduate {y}",
        "{{}} research internship apply",
        "{{}} student mentorship program",
        "{{}} hackathon Bangalore {y}",
        "{{}} hackathon India upcoming registration open",
        "{{}} programming contest {y}",
        "{{}} coding challenge India",
    ]

    queries = []
    for t in topics:
        for template in templates:
            queries.append(template.format(y=year).format(t))

    return queries

def ai_relevance_check(links: list[str]) -> list[str]:
    if not links:
        return []

    print(f"AI filtering {len(links)} links in batches...")
    kept = []
    batch_size = 25

    for i in range(0, len(links), batch_size):
        batch = links[i:i + batch_size]
        numbered = "\n".join(f"{i+1}. {url}" for i, url in enumerate(batch))

        prompt = f"""You are filtering URLs for a fellowship/internship tracker for Indian CS students.

Be LENIENT — when in doubt, KEEP the link.

KEEP if the URL could lead to:
- An official fellowship, internship, mentorship, or scholarship page
- A program timeline, eligibility, or how-to-apply page
- A research internship at any university or institute
- A blog post or announcement FROM the official program org (e.g. cncf.io/blog)

SKIP ONLY if clearly:
- A job aggregator listing (Naukri, Internshala, Glassdoor, Indeed)
- Pure social media post
- Completely unrelated to fellowships/internships/hackathons/contests

Return ONLY a JSON array of numbers to keep. Example: [1, 2, 4, 5, 7]
No explanation, no markdown.

URLs:
{numbered}"""

        raw = ask_ai(prompt, max_tokens=200)
        if not raw:
            kept.extend(batch)
            continue

        parsed = safe_parse_json(raw)
        if not isinstance(parsed, list):
            kept.extend(batch)
            continue

        batch_kept = [batch[i-1] for i in parsed if isinstance(i, int) and 1 <= i <= len(batch)]
        kept.extend(batch_kept)
        print(f"  Batch {i//batch_size + 1}: kept {len(batch_kept)}/{len(batch)}")

    print(f"Total kept: {len(kept)} / {len(links)} links.\n")
    return kept



async def process_link(crawler, run_cfg, link: str, score: int, semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            result = await asyncio.wait_for(
                crawler.arun(url=link, config=run_cfg), timeout=60.0
            )
            
            # Always mark the link as processed to avoid re-scraping in the future
            await discovered_collection.update_one(
                {"apply_link": link},
                {"$set": {
                    "is_processed": True,
                    "last_updated": datetime.now(timezone.utc)
                }},
                upsert=True
            )

            if not result.success or len(result.markdown) < 300:
                return
            if score < 80 and result.markdown.count("](") > 80:
                print(f"Skipping aggregator: {link}")
                return
            
            # Quick keyword pre-filter to save Groq tokens (900+ tokens saved per irrelevant page)
            lower_markdown = result.markdown.lower()
            keywords = ["hackathon", "fellowship", "internship", "research", "mentorship",
                        "scholarship", "contest", "competitive programming", "prize",
                        "stipend", "register", "deadline", "coding challenge"]
            if not any(k in lower_markdown for k in keywords):
                print(f"Skipping (no relevant keywords): {link}")
                return

            links = re.findall(r'https?://[^\s)"]+', result.markdown)

            for l in links[:10]:

                l = normalize_url(l)

                if not is_link_allowed(l):
                    continue

                if get_domain_score(l) < 50:
                    continue

                await discovered_collection.update_one(
                    {"apply_link": l},
                    {"$setOnInsert": {
                    "name": "Discovered Page",
                    "apply_link": l,
                    "trust_score": score - 10,
                    "is_processed": False,
                    "last_updated": datetime.now(timezone.utc)
                }},
                upsert=True
                )
            async with ai_lock:
                details = ai_extract_details(result.markdown, link)

            if not details.get("is_opportunity"):
                print(f"Skipping non-opportunity page: {link}")
                return

            details.pop("is_opportunity", None)

            await asyncio.sleep(1)
            if not details:
                return

            # ── Reject expired opportunities ──
            raw_deadline = details.get("deadline", "")
            if _is_deadline_passed(raw_deadline):
                print(f"Skipping expired opportunity: {link}  (deadline: {raw_deadline})")
                return

            is_open = details.get("is_open")
            if isinstance(is_open, str):
                is_open = is_open.lower() in ["true", "open", "yes"]
            else:
                is_open = bool(is_open)

            doc = {
                "name":         details.get("name") or "Unknown Opportunity",
                "organization": details.get("organization"),
                "deadline":     details.get("deadline", "Check Website"),
                "stipend":      details.get("stipend"),
                "eligibility":  details.get("eligibility"),
                "mode":         details.get("mode"),
                "is_open":      is_open,
                "tags":         details.get("tags", []),
                "apply_link":   link,
                "trust_score":  score,
                "last_updated": datetime.now(timezone.utc),
            }
            
            # Skip transient recurring contests
            if _is_transient_contest(doc["name"]):
                print(f"Skipping transient contest: {doc['name']}")
                return

            # Strict duplicate check by exact name phrase match
            existing_opp = await collection.find_one({
                "name": {"$regex": f"^{re.escape(doc['name'])}$", "$options": "i"}
            })
            if existing_opp:
                print(f"Skipping duplicate insertion: Opportunity '{doc['name']}' already exists.")
                return

            result_db = await collection.update_one({"apply_link": link}, {"$set": doc}, upsert=True)

            if result_db.upserted_id is not None:
              print(f"New opportunity! Sending Discord notification...")
              await send_discord_notification(doc)

            print(f"Saved: {doc['name']}  |  Deadline: {doc['deadline']}")

        except asyncio.TimeoutError:
            print(f"Timeout: {link}")
        except Exception as e:
            print(f"Error ({link}): {e}")

def _is_deadline_passed(deadline_str: str) -> bool:
    """Return True if the deadline date is clearly in the past."""
    if not deadline_str:
        return False
    deadline_str = deadline_str.strip()
    if deadline_str.lower() in ("check website", "rolling", "tba", "tbd", "not specified", ""):
        return False

    today = date.today()

    # Try exact date formats
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y",
                "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            dt = datetime.strptime(deadline_str, fmt).date()
            return dt < today
        except ValueError:
            continue

    # Handle "Month Year" patterns (e.g. "December 2025", "Dec 2025")
    for fmt in ("%B %Y", "%b %Y"):
        try:
            dt = datetime.strptime(deadline_str, fmt)
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            return date(dt.year, dt.month, last_day) < today
        except ValueError:
            continue

    # Handle bare year (e.g. "2025")
    bare_year = re.fullmatch(r"(\d{4})", deadline_str)
    if bare_year:
        yr = int(bare_year.group(1))
        if yr < today.year:
            return True

    return False


def ai_extract_details(page_text: str, url: str) -> dict:
    today = date.today().isoformat()   # e.g. 2026-03-25
    cur_month = date.today().strftime("%B %Y")  # e.g. "March 2026"

    prompt = f"""
Today's date is {today} ({cur_month}).

You are extracting data for a professional opportunity tracker.
Only extract REAL, NAMED programs — not generic advice articles, blog posts, or listicles.

CRITICAL DATE RULES:
- If the page mentions ANY deadline, registration close date, or event date that is BEFORE {today}, return {{ "is_opportunity": false }}.
- If the page describes an event/program from a PREVIOUS year (e.g. 2024, 2025) and does NOT mention {date.today().year} or later, return {{ "is_opportunity": false }}.
- If you cannot confirm the opportunity is CURRENTLY open for registration/application OR opens in the future, return {{ "is_opportunity": false }}.
- When in doubt about dates, return {{ "is_opportunity": false }}.

Also return {{ "is_opportunity": false }} if:
- The page is a news article, opinion piece, or generic tips page
- The page lists many opportunities but is not an official page for ONE specific program
- The page is about results/winners of a past edition

Otherwise return:

{{
  "is_opportunity": true,
  "name": "Full program name",
  "organization": "Sponsoring organization",
  "deadline": "YYYY-MM-DD or Check Website or Rolling",
  "stipend": "Amount or Unpaid or Not Specified",
  "eligibility": "1-2 sentence summary",
  "mode": "Remote or In-Person or Hybrid",
  "is_open": true or false (based on whether the deadline is on or after {today}),
  "tags": ["fellowship", "hackathon", "CP contest", etc.]
}}

URL:
{url}

Content:
{page_text[:5000]}
"""

    raw = ask_ai(prompt, max_tokens=900)

    if not raw:
        return {}

    result = safe_parse_json(raw)

    if not isinstance(result, dict):
        return {}

    return result

async def ensure_indexes():
    await collection.create_index("apply_link", unique=True)
    await collection.create_index("last_updated")

async def ping_mongo():
    await mongo_client.admin.command("ping")

async def cleanup_expired_entries():
    """Mark opportunities with clearly-past deadlines as is_open=false."""
    today = date.today()
    cursor = collection.find({"is_open": True})
    marked = 0
    async for doc in cursor:
        raw_deadline = doc.get("deadline", "")
        if _is_deadline_passed(raw_deadline):
            await collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"is_open": False}}
            )
            marked += 1
    if marked:
        print(f"🧹 Marked {marked} expired entries as closed.")

async def main(mode: str = "full"):
    await ping_mongo()
    await ensure_indexes()
    await cleanup_expired_entries()
    print("=" * 60)
    print(f"  FELLOWSHIP TRACKER — {mode.upper()} MODE")
    print(f"  Model: {GROQ_MODEL}")
    print("=" * 60)

    programs = []

    # Must-have programs — heavy AI query generation, run weekly
    if mode in ("weekly", "full"):
        print("\n📌 Including must-have programs (weekly)")
        programs.extend(generate_queries_with_ai())

    # Discovery + dynamic queries — lightweight, run daily
    if mode in ("daily", "full"):
        print("\n🔎 Including discovery queries (daily)")
        for q in build_discovery_queries():
            programs.append({
                "name": "Discovery",
                "queries": [q],
                "official_domain_hint": ""
            })
        for q in generate_dynamic_queries():
            programs.append({
                "name": "DynamicSearch",
                "queries": [q],
                "official_domain_hint": ""
            })

    if not programs:
        print("❌ No programs to search. Check --mode flag.")
        return

    tbs_filter = "qdr:m" if mode == "daily" else "qdr:m3"  # tighter for daily
    print(f"\n📡 Running web searches (recency: {tbs_filter})...\n")
    scored_links = await collect_links(programs, tbs=tbs_filter)

    if not scored_links:
        print(" No links found. Check SERPER_API_KEY in .env")
        return

    scored_links  = deduplicate_by_domain(scored_links, max_per_domain=2)
    for domain in DISCOVERY_DOMAINS:
        for path in generate_domain_paths(domain):
            scored_links.append((85, normalize_url(path)))

    scored_links = list(set(scored_links))
    existing_urls = await get_existing_urls()
    
    fresh_links = [(sc, url) for sc, url in scored_links if url not in existing_urls]
    print(f" {len(fresh_links)} new links to process ({len(scored_links) - len(fresh_links)} already in DB, skipping)\n")

    top_urls   = [url for _, url in fresh_links[:150]]
    final_urls = top_urls
    score_map  = {url: sc for sc, url in scored_links}

    print(f"\n Crawling {len(final_urls)} pages...\n")
    semaphore = asyncio.Semaphore(3)
    run_cfg   = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        exclude_all_images=True,
        page_timeout=60000,
        wait_for="body",
        delay_before_return_html=2.0,
    )

    async with AsyncWebCrawler() as crawler:
        tasks = [
            process_link(crawler, run_cfg, url, score_map.get(url, 50), semaphore)
            for url in final_urls
        ]
        await asyncio.gather(*tasks)

    print("\n Done! Database updated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fellowship Tracker Scraper")
    parser.add_argument(
        "--mode",
        choices=["daily", "weekly", "full"],
        default="full",
        help="daily = discovery queries only, weekly = must-have programs only, full = everything (default)",
    )
    args = parser.parse_args()
    asyncio.run(main(mode=args.mode))