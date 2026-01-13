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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/110.0"
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
                        context = (r.get('title', '') + r.get('snippet', '')).lower()
                        if not link.lower().endswith('.pdf') and any(k in context for k in ['intern', 'fellow', 'scholar', 'trainee']):
                            all_links.add(link)
                    await asyncio.sleep(0.5)
                except Exception as e: print(f"⚠️ Search Error: {e}")
    return list(all_links)

async def process_link(crawler, run_cfg, link, semaphore):
    async with semaphore:
        try:
            # Set a master timeout for this specific page visit
            result = await asyncio.wait_for(crawler.arun(url=link, config=run_cfg), timeout=60.0)
            
            # QUALITY CHECK: Only save if page content is substantial
            if result.success and len(result.markdown) > 500:
                name = clean_name(result.markdown, result.metadata.get('title', ''))
                deadline = extract_deadline(result.markdown)
                
                # UPSERT: Update existing or add new
                supabase.table("fellowships").upsert({
                    "name": name,
                    "deadline": deadline,
                    "apply_link": link
                }, on_conflict="apply_link").execute()
                print(f"✅ Synced: {name}")
        except Exception as e:
            print(f"🕒 Skipped {link}: {e}")

async def main():
    links = await discover_300_links()
    if not links: return
    semaphore = asyncio.Semaphore(3)

    # Browser config to block heavy assets and prevent "Sticking"
    browser_cfg = BrowserConfig(headless=True, extra_args=["--disable-gpu", "--no-sandbox"])
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        exclude_all_images=True, 
        page_timeout=35000, 
        wait_for="body"
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        print(f"🚀 Processing {len(links)} links in parallel...")

        tasks = [process_link(crawler, run_cfg, link, semaphore) for link in links]

        await asyncio.gather(*tasks)
        print("🎉 Database sync complete.")

if __name__ == "__main__":
    asyncio.run(main())