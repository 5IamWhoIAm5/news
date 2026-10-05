import feedparser
import os
import time
import calendar
import html
import json
import datetime
import re
import requests
from difflib import SequenceMatcher
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

# --- CONFIGURATION & INIT ---
api_key = os.environ.get("GEMINI_API_KEY")
client = None

if not api_key:
    print("🚨 CRITICAL ERROR: GEMINI_API_KEY is missing or empty!")
else:
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"Gemini init error: {e}")

now_ts = time.time()
ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
now_dt_ist = datetime.datetime.now(ist_tz)
build_time_str = now_dt_ist.strftime("%b %d, %H:%M IST")

FEEDS = {
    "PUNE (LOCAL)": [
        ("Hindustan Times Pune", "https://www.hindustantimes.com/feeds/rss/cities/pune-news/rssfeed.xml"),
        ("Indian Express Pune", "https://indianexpress.com/section/cities/pune/feed/"),
        ("Times of India Pune", "https://timesofindia.indiatimes.com/rssfeeds/-2128821991.cms")
    ],
    "INDIA": [
        ("NDTV India", "https://feeds.feedburner.com/ndtvnews-india-news"),
        ("Indian Express", "https://indianexpress.com/section/india/feed/"),
        ("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms")
    ],
    "WORLD": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("NYT World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml")
    ],
    "TECH": [
        ("TechCrunch", "https://feeds.feedburner.com/TechCrunch/"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("Verge", "https://www.theverge.com/rss/index.xml")
    ],
    "BUSINESS": [
        ("Economic Times Corporate", "https://economictimes.indiatimes.com/news/company/rssfeeds/2143429.cms"),
        ("Moneycontrol Business", "https://www.moneycontrol.com/rss/business.xml"),
        ("Livemint Companies", "https://www.livemint.com/rss/companies")
    ],
    "AUTO": [
        ("Autocar India", "https://www.autocarindia.com/rss/all"),
        ("MotorOctane", "https://motoroctane.com/feed")
    ],
    "SPORTS": [
        ("ESPN Cricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"),
        ("NDTV Sports", "https://feeds.feedburner.com/ndtvsports-latest"),
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml")
    ]
}

TECH_KEYWORDS = {"amd", "nvidia", "intel", "apple", "google", "microsoft", "openai", "qualcomm", "semiconductor", "chip", "chips", "ai", "software", "tech", "gadget", "smartphone"}
AUTO_KEYWORDS = {"car", "cars", "suv", "ev", "electric vehicle", "motor", "auto", "vehicle", "hybrid", "rover", "jlr", "tata motors", "maruti", "hyundai", "bmw", "mercedes", "audi"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/"
}

# --- TEXT CLEANING & HELPER FUNCTIONS ---
def fix_encoding(text):
    if not text: return ""
    try: text = text.encode('latin-1').decode('utf-8')
    except Exception: pass
    text = html.unescape(text)
    replacements = {'â€™': "'", 'â€œ': '"', 'â€': '"', 'â€”': '—', 'â€“': '–', 'Â': ''}
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text

def clean_boilerplate(text):
    if not text: return ""
    junk_patterns = [
        r"be respectful\s*[·•|-]?\s*toi community guidelines.*",
        r"toi community guidelines.*",
        r"community guidelines.*",
        r"follow us on\s+.*",
        r"subscribe to\s+.*",
        r"click here to\s+.*",
        r"copyright\s*©.*",
        r"all rights reserved.*",
        r"read more at:?.*",
        r"also read:?.*",
        r"must read:?.*",
        r"^event updates:?\s*"
    ]
    for pattern in junk_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()

def clean_text(raw_html):
    if not raw_html: return ""
    text = re.sub(r'<[^>]+>', ' ', raw_html)
    text = fix_encoding(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return clean_boilerplate(text)

def normalize_title(title):
    return re.sub(r'^(pune news|pune|india news|city news|breaking|watch|live|update|opinion|review):?\s*', '', title, flags=re.IGNORECASE).strip()

def sanitize_truncated_endings(text):
    if not text: return ""
    text = re.sub(r'\b\w+\.\.\.+$', '', text).strip()
    return re.sub(r'(\.\.\.|\…)+$', '', text).strip()

def is_unwanted_article(title, content):
    if not title or len(title) < 10: return True
    combined = f"{title} {content}".lower()
    unwanted_patterns = [
        "stock market live", "sensex", "nifty", "trade flat", "opening bell",
        "market live updates", "rupee opens", "equity benchmarks", "stocks to watch",
        "opinion:", "editorial:", "my take:", "buying guide", "should you buy",
        "top 10", "best deals", "hands-on review", "our verdict", "why you should",
        "perspective:", "viewpoint:", "review:", "toi community guidelines", "be respectful"
    ]
    return any(p in combined for p in unwanted_patterns)

def get_full_article_content(entry, url):
    summary = clean_text(entry.get('summary', entry.get('description', '')))
    if hasattr(entry, 'content') and entry.content:
        for c in entry.content:
            val = clean_text(c.get('value', ''))
            if len(val) > 200 and not val.endswith('...'):
                return val[:1500]

    needs_scrape = len(summary) < 250 or summary.endswith('...') or summary.endswith('…') or '...' in summary[-20:]

    if url and url != '#' and needs_scrape:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=5)
            if resp.status_code == 200:
                resp.encoding = 'utf-8'
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                meta_desc = ""
                for meta in soup.find_all('meta'):
                    m_name = meta.get('name', '').lower()
                    m_prop = meta.get('property', '').lower()
                    if m_name in ['description', 'og:description', 'twitter:description'] or \
                       m_prop in ['og:description', 'twitter:description']:
                        c_val = clean_text(meta.get('content', ''))
                        if len(c_val) > len(meta_desc):
                            meta_desc = c_val

                for s in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'noscript']):
                    s.decompose()
                paragraphs = soup.find_all('p')
                p_texts = [clean_text(p.get_text()) for p in paragraphs if len(clean_text(p.get_text())) > 35]
                scraped_p = " ".join(p_texts[:4])
                
                best_scraped = scraped_p if len(scraped_p) > 150 else meta_desc
                if len(best_scraped) > len(summary):
                    return best_scraped[:1500]
        except Exception:
            pass
            
    summary_clean = sanitize_truncated_endings(summary)
    return summary_clean if len(summary_clean) >= 30 else entry.get('title', '')

def parse_time_info(parsed_time):
    if not parsed_time:
        return ("24h", "Today", 0, now_ts)
    try:
        pub_ts = calendar.timegm(parsed_time)
        diff_sec = max(0, int(now_ts - pub_ts))
        diff_hours = diff_sec / 3600.0
        
        if diff_sec < 3600: time_ago = f"{max(1, diff_sec // 60)}m ago"
        elif diff_sec < 86400: time_ago = f"{int(diff_hours)}h ago"
        else: time_ago = f"{diff_sec // 86400}d ago"

        if diff_hours <= 24: return ("24h", time_ago, diff_hours, pub_ts)
        elif diff_hours <= 48: return ("48h", time_ago, diff_hours, pub_ts)
        elif diff_hours <= 72: return ("72h", time_ago, diff_hours, pub_ts)
        else: return ("discard", time_ago, diff_hours, pub_ts)
    except Exception:
        return ("24h", "Today", 0, now_ts)

def determine_canonical_category(title, content, feed_tag):
    combined = f"{title} {content}".lower()
    def has_exact_keyword(keywords, text):
        return any(re.search(rf'\b{re.escape(k)}\b', text) for k in keywords)

    if feed_tag == "PUNE (LOCAL)" or bool(re.search(r'\bpune\b', combined)): return "PUNE (LOCAL)"
    if feed_tag in ["SPORTS", "AUTO", "TECH", "BUSINESS"]: return feed_tag
    if has_exact_keyword(AUTO_KEYWORDS, combined): return "AUTO"
    if has_exact_keyword(TECH_KEYWORDS, combined): return "TECH"
    return feed_tag

STOPWORDS = {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with", "is", "are", "was", "were", "by", "as", "from", "it", "this", "that", "its", "new", "vs", "has", "have", "after", "pune", "billion", "million"}

def get_title_keywords(title):
    return set(w for w in re.findall(r'\w+', title.lower()) if w not in STOPWORDS and len(w) > 2)

def is_same_story(title1, title2):
    kw1, kw2 = get_title_keywords(title1), get_title_keywords(title2)
    if not kw1 or not kw2: return False
    overlap = kw1.intersection(kw2)
    jaccard = len(overlap) / float(len(kw1.union(kw2)))
    seq_ratio = SequenceMatcher(None, title1.lower(), title2.lower()).ratio()
    
    if len(overlap) >= 2 and any(w in TECH_KEYWORDS or w in AUTO_KEYWORDS or len(w) > 5 for w in overlap): return True
    return jaccard >= 0.35 or seq_ratio >= 0.55

def generate_fallback_takeaways(title, content):
    c_clean = clean_boilerplate(content)
    if c_clean.lower().startswith(title.lower()):
        c_clean = c_clean[len(title):].strip()
        
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', c_clean) if len(s.strip()) > 25]
    valid = [s for s in sentences if not any(j in s.lower() for j in ["guideline", "respectful", "comment", "copyright", "subscribe"])]
    
    if valid: return valid[:2]
    return [c_clean] if len(c_clean) > 20 else [title]


# --- MAIN PIPELINE ---

# 1. Fetch feed entries
print("Fetching RSS feeds...")
all_fetched_articles = []
for tag, feed_list in FEEDS.items():
    fetch_limit = 10 if "PUNE" in tag else 6
    for source_name, feed_url in feed_list:
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:fetch_limit]:
                group_key, time_ago, hours_old, pub_ts = parse_time_info(entry.get('published_parsed') or entry.get('updated_parsed'))
                if group_key == "discard": continue
                
                raw_title = clean_text(entry.get('title', ''))
                link = entry.get('link', '#')
                full_content = get_full_article_content(entry, link)
                
                if is_unwanted_article(raw_title, full_content): continue
                    
                clean_t = normalize_title(raw_title)
                assigned_category = determine_canonical_category(clean_t, full_content, tag)

                all_fetched_articles.append({
                    "category": assigned_category,
                    "source": source_name,
                    "title": raw_title,
                    "clean_title": clean_t,
                    "content": full_content,
                    "link": link,
                    "pub_ts": pub_ts,
                    "group_key": group_key,
                    "time_ago": time_ago
                })
        except Exception as e:
            print(f"Error fetching {source_name}: {e}")

# 2. Global Deduplication
print("Deduplicating stories...")
global_clusters = []
for art in all_fetched_articles:
    matched = False
    for cluster in global_clusters:
        if is_same_story(art["clean_title"], cluster["clean_title"]):
            if not any(s["source"] == art["source"] for s in cluster["sources"]):
                cluster["sources"].append({"source": art["source"], "link": art["link"]})
            
            category_priority = ["PUNE (LOCAL)", "AUTO", "TECH", "BUSINESS", "SPORTS", "INDIA", "WORLD"]
            if category_priority.index(art["category"]) < category_priority.index(cluster["category"]):
                cluster["category"] = art["category"]
                
            if len(art["content"]) > len(cluster["content"]):
                cluster["content"] = art["content"]
                
            if art["pub_ts"] > cluster["pub_ts"]:
                cluster["pub_ts"] = art["pub_ts"]
                cluster["time_ago"] = art["time_ago"]
                cluster["group_key"] = art["group_key"]
                
            matched = True
            break
            
    if not matched:
        global_clusters.append({
            "category": art["category"],
            "title": art["title"],
            "clean_title": art["clean_title"],
            "content": art["content"],
            "pub_ts": art["pub_ts"],
            "group_key": art["group_key"],
            "time_ago": art["time_ago"],
            "sources": [{"source": art["source"], "link": art["link"]}]
        })

# 3. Map items for API processing
llm_input_list = []
item_lookup = {}
all_clusters_map = {}

for cluster in global_clusters:
    tag = cluster["category"]
    if tag not in all_clusters_map: all_clusters_map[tag] = []
    all_clusters_map[tag].append(cluster)

for tag, clusters in all_clusters_map.items():
    clusters.sort(key=lambda x: x["pub_ts"], reverse=True)
    for i, c in enumerate(clusters[:8]):
        uid = f"{tag}|||{i}"
        item_lookup[uid] = c
        llm_input_list.append({"id": uid, "title": c["title"], "text": c["content"][:800]})

# 4. HYBRID API CALL: Mini-Batches to prevent hallucination & respect rate limits
llm_results_list = []

if client and llm_input_list:
    BATCH_SIZE = 5 # Process 5 articles per API call to balance speed, rate limits, and accuracy.
    active_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
    
    def chunker(seq, size):
        return [seq[pos:pos + size] for pos in range(0, len(seq), size)]
        
    chunks = chunker(llm_input_list, BATCH_SIZE)
    print(f"\nSending {len(llm_input_list)} articles to Gemini in {len(chunks)} mini-batches of {BATCH_SIZE}...")

    for chunk_idx, chunk in enumerate(chunks):
        expected_ids = {item["id"] for item in chunk}
        
        prompt = f"""You are a precise news editor. You will receive a batch of {len(chunk)} independent news articles.
For EACH article in the input array, you must generate exactly ONE output object containing a clear headline and 2 factual bullet takeaways.

CRITICAL RULES TO PREVENT DATA MIXING:
1. STRICT ISOLATION: Never mix facts, names, or events from one article into another's summary.
2. Return an array of exactly {len(chunk)} objects.
3. You MUST preserve and return the exact "id" string provided for each article.
4. Never output filler text like "Event updates" or website guidelines.

INPUT JSON:
{json.dumps(chunk, indent=2)}

OUTPUT FORMAT:
Return ONLY a valid JSON array of objects matching this structure:
[
  {{
    "id": "EXACT_ID_FROM_INPUT",
    "headline": "Clear concise headline",
    "takeaways": ["First key factual detail.", "Second key factual detail."]
  }}
]
"""
        success = False
        for model_name in active_models:
            if success: break
            
            for attempt in range(3): # Retry for 429/503 errors
                try:
                    res = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.0, # Zero temperature prevents creative hallucination
                            max_output_tokens=2000,
                            response_mime_type="application/json",
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                        )
                    )
                    
                    if res and res.text:
                        batch_results = json.loads(res.text)
                        
                        # Validate that the AI returned what we asked for
                        returned_ids = {item.get("id") for item in batch_results if isinstance(item, dict)}
                        missing_ids = expected_ids - returned_ids
                        if missing_ids:
                            print(f"  ⚠ AI missed IDs {missing_ids} in this batch. Falling back.")
                            
                        for res_item in batch_results:
                            if res_item.get("id") in expected_ids:
                                llm_results_list.append(res_item)
                                
                        success = True
                        print(f"  ✅ Batch [{chunk_idx+1}/{len(chunks)}] processed via {model_name}")
                        time.sleep(2) # Prevent Free Tier RPM limiting
                        break
                        
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "503" in err_str:
                        print(f"  ⏳ Rate limit hit. Backing off {5 * (attempt + 1)}s...")
                        time.sleep(5 * (attempt + 1))
                    else:
                        print(f"  ❌ JSON Parse error on Batch {chunk_idx+1}: {err_str}")
                        break 
                        
        if not success:
            print(f"  🚨 Batch [{chunk_idx+1}/{len(chunks)}] failed. Using fallback text.")

# 5. Process categories and apply fallbacks
processed_categories = {tag: [] for tag in all_clusters_map.keys()}

if isinstance(llm_results_list, list):
    for res_item in llm_results_list:
        uid = res_item.get("id")
        if not uid or uid not in item_lookup: continue
        tag, idx = uid.split("|||")
        
        c_title = item_lookup[uid]["title"]
        c_content = item_lookup[uid]["content"]
        raw_takeaways = res_item.get("takeaways", [])
        
        cleaned_takeaways = []
        for t in raw_takeaways:
            if t and isinstance(t, str) and len(t) > 15:
                cleaned = clean_boilerplate(t)
                if cleaned: cleaned_takeaways.append(cleaned)
                
        if not cleaned_takeaways:
            cleaned_takeaways = generate_fallback_takeaways(c_title, c_content)

        processed_categories[tag].append({
            "original_cluster": item_lookup[uid],
            "headline": res_item.get("headline", c_title),
            "takeaways": cleaned_takeaways[:2]
        })

# 6. Build UI HTML
print("\nBuilding HTML output...")
html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Micro News</title>
<style>
  :root {{ --bg: #090a0f; --card-bg: #13151c; --text: #e2e8f0; --text-muted: #94a3b8; --accent: #38bdf8; --border: #1e293b; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 12px; max-width: 650px; margin: 0 auto; padding-bottom: 60px; }}
  header {{ padding: 12px 4px 8px; margin-bottom: 12px; }}
  .header-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
  h1 {{ font-size: 20px; font-weight: 800; letter-spacing: -0.5px; color: #fff; }}
  .refresh-badge {{ font-size: 11px; color: var(--text-muted); background: #1a1d26; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--border); }}
  .tabs {{ display: flex; gap: 8px; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 16px; }}
  .tab-btn {{ flex: 1; padding: 8px 12px; background: #13151c; border: 1px solid var(--border); color: var(--text-muted); font-size: 13px; font-weight: 700; border-radius: 8px; cursor: pointer; text-align: center; }}
  .tab-btn.active {{ background: var(--accent); color: #000; border-color: var(--accent); }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
  h2 {{ color: var(--accent); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.2px; margin: 22px 4px 10px; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 12px; overflow: hidden; }}
  details {{ width: 100%; }}
  summary {{ padding: 12px 14px; font-size: 14.5px; line-height: 1.4; font-weight: 700; cursor: pointer; list-style: none; color: #f8fafc; display: flex; align-items: flex-start; gap: 10px; }}
  summary::-webkit-details-marker {{ display: none; }}
  .bullet {{ color: var(--accent); font-weight: bold; font-size: 18px; line-height: 1; flex-shrink: 0; margin-top: 2px; }}
  .time-badge {{ background: #1e293b; color: #94a3b8; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }}
  .summary-text {{ flex-grow: 1; }}
  .details-content {{ padding: 14px 16px 16px 20px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 13.5px; color: #cbd5e1; line-height: 1.55; background: rgba(0,0,0,0.2); }}
  .takeaways-list {{ margin: 0 0 14px 0; padding-left: 18px; list-style-type: disc; }}
  .takeaways-list li {{ margin-bottom: 8px; color: #e2e8f0; font-size: 13px; line-height: 1.5; }}
  .sources-header {{ margin-bottom: 12px; padding: 8px 10px; background: rgba(56, 189, 248, 0.08); border-radius: 6px; border-left: 3px solid var(--accent); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .sources-label {{ font-size: 10px; font-weight: 800; color: var(--accent); text-transform: uppercase; letter-spacing: 0.8px; }}
  .source-btn {{ display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; background: #1e293b; color: #f1f5f9; text-decoration: none; border-radius: 4px; font-size: 11px; font-weight: 700; border: 1px solid var(--border); transition: background 0.15s; }}
  .source-btn:hover {{ background: var(--accent); color: #000; }}
  .no-news {{ color: var(--text-muted); font-size: 13px; padding: 12px; text-align: center; }}
</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1>Micro News</h1>
    <span class="refresh-badge">Refreshed: {build_time_str}</span>
  </div>
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('24h')">Last 24h</button>
    <button class="tab-btn" onclick="switchTab('48h')">24-48h</button>
    <button class="tab-btn" onclick="switchTab('72h')">Older</button>
  </div>
</header>
<div id="tab-24h" class="tab-content active">
"""

tab_data = {"24h": "", "48h": "", "72h": ""}
category_order = ["PUNE (LOCAL)", "AUTO", "TECH", "SPORTS", "BUSINESS", "INDIA", "WORLD"]

for tag in sorted(all_clusters_map.keys(), key=lambda t: category_order.index(t) if t in category_order else 99):
    clusters = all_clusters_map[tag]
    items = processed_categories.get(tag, [])
    processed_titles = {item["original_cluster"]["title"] for item in items}
    
    # Fill in any missing items that were skipped by AI/Failed batches
    for c in clusters[:8]:
        if c["title"] not in processed_titles:
            items.append({
                "original_cluster": c,
                "headline": c["title"],
                "takeaways": generate_fallback_takeaways(c["title"], c["content"])
            })
            
    items.sort(key=lambda x: x["original_cluster"]["pub_ts"], reverse=True)
    cat_tab_html = {"24h": "", "48h": "", "72h": ""}
    
    for item in items:
        c = item["original_cluster"]
        group_key = c["group_key"]
        headline = re.sub(r'^(Watch|LIVE|BREAKING):?\s*', '', item["headline"], flags=re.IGNORECASE)
        valid_takeaways = item["takeaways"]
            
        takeaways_html = "".join([f"<li>{html.escape(t)}</li>" for t in valid_takeaways])
        sources_html = "".join([f'<a href="{s["link"]}" target="_blank" class="source-btn">{s["source"]} ↗</a>' for s in c["sources"]])
                
        card_html = f"""
        <div class="card">
          <details name="news-card">
            <summary>
              <span class="bullet">•</span>
              <span class="summary-text">{html.escape(headline)}</span>
              <span class="time-badge">{c["time_ago"]}</span>
            </summary>
            <div class="details-content">
              <div class="sources-header">
                <span class="sources-label">Sources:</span>
                {sources_html}
              </div>
              <ul class="takeaways-list">
                {takeaways_html}
              </ul>
            </div>
          </details>
        </div>
        """
        cat_tab_html[group_key] += card_html

    for gk in ["24h", "48h", "72h"]:
        if cat_tab_html[gk]:
            tab_data[gk] += f"<h2>{tag}</h2>" + cat_tab_html[gk]

html_out += tab_data["24h"] if tab_data["24h"] else "<div class='no-news'>No news in the last 24 hours.</div>"
html_out += '</div><div id="tab-48h" class="tab-content">'
html_out += tab_data["48h"] if tab_data["48h"] else "<div class='no-news'>No news between 24 and 48 hours ago.</div>"
html_out += '</div><div id="tab-72h" class="tab-content">'
html_out += tab_data["72h"] if tab_data["72h"] else "<div class='no-news'>No older news available.</div>"

html_out += """
</div>
<script>
function switchTab(tabName) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + tabName).classList.add('active');
  event.target.classList.add('active');
}
// Accordion behavior: close others when one opens
document.querySelectorAll('details').forEach((el) => {
  el.addEventListener('toggle', (e) => {
    if (el.open) {
      document.querySelectorAll('details').forEach((otherEl) => {
        if (otherEl !== el) { otherEl.open = false; }
      });
    }
  });
});
</script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_out)
    
print("✅ Done! Saved output to index.html")
