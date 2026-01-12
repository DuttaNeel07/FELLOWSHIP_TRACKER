import asyncio
import os
import re
import httpx
from urllib.parse import urljoin
from dotenv import load_dotenv
from supabase import create_client, Client
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# 1. SETUP & CONFIGURATION
load_dotenv()
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
SERPER_KEY = os.getenv("SERPER_API_KEY")

# High-Precision Queries for 300+ Indian Tech Links
SEARCH_QUERIES = [
    "site:gov.in tech fellowship 2026 application",
    "site:edu.in software engineering internship summer 2026",
    "MeitY digital india internship 2026 registration",
    "ISRO IIRS internship for students 2026",
    "IIT research internship 2026 computer science",
    "software developer internship india 2026 apply",
    "AI ML fellowship for indian students 2026",
    "Google India STEP internship 2026 deadline",
    "Microsoft India university internship 2026",
    "Qualcomm India technical internship 2026"
]

def clean_name(markdown, metadata_title):
    """Surgically extracts the cleanest fellowship name."""
    h1_match = re.search(r'^#\s+(.*)', markdown, re.MULTILINE)
    name = h1_match.group(1).strip() if h1_match else metadata_title
    noise = ['|', '-', 'Registration', 'Apply Now', '2026', '2025', 'Home', 'Login']
    for word in noise:
        name = name.split(word)[0].strip()
    return name[:80] if name else "Indian Tech Opportunity"

def extract_deadline(text):
    """Refined for Indian date styles (e.g. 28th Feb, 31/03/2026)."""
    patterns = [
        r'\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*',
        r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}'
    ]
    for p in patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match: return match.group(0).strip()
    return "Check Website"

async def discover_300_links():
    """Loops through queries and pages to find a massive link set."""
    all_links = set()
    async with httpx.AsyncClient() as client:
        for query in SEARCH_QUERIES:
            for page in range(1, 4): # Get 3 pages per query for wider reach
                print(f"🌍 Searching: '{query}' (Page {page})")
                payload = {"q": query, "gl": "in", "num": 50, "page": page}
                headers = {'X-API-KEY': SERPER_KEY, 'Content-Type': 'application/json'}
                try:
                    resp = await client.post("https://google.serper.dev/search", json=payload, headers=headers)
                    results = resp.json().get('organic', [])
                    for r in results:
                        link = r['link']
                        if any(k in link.lower() for k in ['fellow', 'intern', 'scholar', 'program']):
                            all_links.add(link)
                except Exception as e: print(f"⚠️ Search Error: {e}")
    return list(all_links)

async def main():
    links = await discover_300_links()
    if not links: return

    # Browser config to block heavy assets and prevent "Sticking"
    browser_cfg = BrowserConfig(headless=True, extra_args=["--disable-gpu", "--no-sandbox"])
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        exclude_all_images=True, 
        page_timeout=35000, 
        wait_for="body"
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        print(f"🗑️ Found {len(links)} global links. Clearing DB and deep-scanning...")
        #supabase.table("fellowships").delete().neq("id", 0).execute()

        for i, link in enumerate(links[:300]): # Limit to top 300 unique results
            print(f"🔄 Processing ({i+1}/{len(links)}): {link}")
            try:
                # Master timeout per link to prevent hanging
                result = await asyncio.wait_for(crawler.arun(url=link, config=run_cfg), timeout=50.0)
                if result.success:
                    name = clean_name(result.markdown, result.metadata.get('title', ''))
                    deadline = extract_deadline(result.markdown)
                    
                    
                    supabase.table("fellowships").upsert({
                        "name": name,
                        "deadline": deadline,
                        "apply_link": link
                    }, on_conflict="apply_link").execute()
                    
                    print(f"✅ Synced: {name}")
                await asyncio.sleep(1.5) # Gentle rate-limiting
            except Exception: print(f"🕒 Skipped (Timeout/Error): {link}")

if __name__ == "__main__":
    asyncio.run(main())