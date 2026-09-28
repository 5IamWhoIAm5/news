import feedparser, os, time, calendar, html, json, datetime, re, requests
from difflib import SequenceMatcher
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

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

def fix_encoding(text):
    if not text:
        return ""
    try:
        text = text.encode('latin-1').decode('utf-8')
    except Exception:
        pass
    text = html.unescape(text)
    replacements = {'â€™': "'", 'â€œ': '"', 'â€': '"', 'â€”': '—', 'â€“': '–', 'Â': ''}
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text

def clean_text(raw_html):
    if not raw_html:
        return ""
    text = re.sub(r'<[^>]+>', ' ', raw_html)
    text = fix_encoding(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def normalize_title(title):
    """Strips city/source prefixes so matching works across different news outlets."""
    title = re.sub(r'^(pune news|pune|india news|city news|breaking|watch|live|update):?\s*', '', title, flags=re.IGNORECASE)
    return title.strip()

def sanitize_truncated_endings(text):
    if not text:
        return ""
    text = re.sub(r'\b\w+\.\.\.+$', '', text).strip()
    text = re.sub(r'(\.\.\.|\…)+$', '', text).strip()
    return text

def is_unwanted_article(title, content):
    combined = f"{title} {content}".lower()
    unwanted_patterns = [
        "stock market live", "sensex", "nifty", "trade flat", "opening bell",
        "market live updates", "rupee opens", "equity benchmarks", "stocks to watch",
        "opinion:", "editorial:", "my take:", "buying guide", "should you buy",
        "top 10", "best deals", "hands-on review", "our verdict", "why you should",
        "perspective:", "viewpoint:", "review:"
    ]
    return any(p in combined for p in unwanted_patterns)

def get_full_article_content(entry, url):
    summary = clean_text(entry.get('summary', entry.get('description', '')))
    
    if hasattr(entry, 'content') and entry.content:
        for c in entry.content:
            val = clean_text(c.get('value', ''))
            if len(val) > 250 and not val.endswith('...'):
                return val[:2500]

    needs_scrape = len(summary) < 500 or summary.endswith('...') or summary.endswith('…') or '...' in summary[-20:]

    if url and url != '#' and needs_scrape:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                resp.encoding = 'utf-8'
                soup = BeautifulSoup(resp.text, 'html.parser')
                for s in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'noscript']):
                    s.decompose()
                paragraphs = soup.find_all('p')
                p_texts = [clean_text(p.get_text()) for p in paragraphs if len(clean_text(p.get_text())) > 35]
                scraped_text = " ".join(p_texts[:8])
                if len(scraped_text) > len(summary):
                    return scraped_text[:2500]
        except Exception:
            pass
            
    return sanitize_truncated_endings(summary)

def parse_time_info(parsed_time):
    if not parsed_time:
        return ("today", "Today", 0, now_ts)
    try:
        pub_ts = calendar.timegm(parsed_time)
        pub_dt_ist = datetime.datetime.fromtimestamp(pub_ts, tz=datetime.timezone.utc).astimezone(ist_tz)
        
        diff_sec = max(0, int(now_ts - pub_ts))
        if diff_sec < 3600:
            time_ago = f"{max(1, diff_sec // 60)}m ago"
        elif diff_sec < 86400:
            time_ago = f"{diff_sec // 3600}h ago"
        else:
            days = diff_sec // 86400
            time_ago = f"{days}d ago"

        pub_date = pub_dt_ist.date()
        today_date = now_dt_ist.date()
        day_diff = (today_date - pub_date).days

        if day_diff <= 0:
            return ("today", time_ago, day_diff, pub_ts)
        elif day_diff == 1:
            return ("yesterday", time_ago, day_diff, pub_ts)
        elif day_diff in [2, 3]:
            return ("older", time_ago, day_diff, pub_ts)
        else:
            return ("discard", time_ago, day_diff, pub_ts)
    except Exception:
        return ("today", "Today", 0, now_ts)

# Zero-Token Deduplication Logic
STOPWORDS = {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with", "is", "are", "was", "were", "by", "as", "from", "it", "this", "that", "its", "new", "vs", "has", "have", "after", "pune"}

def get_title_keywords(title):
    words = re.findall(r'\w+', title.lower())
    return set(w for w in words if w not in STOPWORDS and len(w) > 2)

def is_same_story(title1, title2):
    kw1 = get_title_keywords(title1)
    kw2 = get_title_keywords(title2)
    if not kw1 or not kw2:
        return False
        
    jaccard = len(kw1.intersection(kw2)) / float(len(kw1.union(kw2)))
    seq_ratio = SequenceMatcher(None, title1.lower(), title2.lower()).ratio()
    
    return jaccard >= 0.35 or seq_ratio >= 0.55

# 1. Fetch ALL articles globally across feeds first
all_fetched_articles = []

for tag, feed_list in FEEDS.items():
    fetch_limit = 12 if "PUNE" in tag else 8
    for source_name, feed_url in feed_list:
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries[:fetch_limit]:
            group_key, time_ago, days_old, pub_ts = parse_time_info(entry.get('published_parsed') or entry.get('updated_parsed'))
            if group_key == "discard":
                continue
            raw_title = clean_text(entry.get('title', ''))
            link = entry.get('link', '#')
            full_content = get_full_article_content(entry, link)
            
            if is_unwanted_article(raw_title, full_content):
                continue
                
            clean_t = normalize_title(raw_title)
            
            # Route Pune stories exclusively to PUNE (LOCAL)
            assigned_category = tag
            if assigned_category == "INDIA" and "pune" in clean_t.lower():
                assigned_category = "PUNE (LOCAL)"

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

# 2. Global Deduplication Across ALL Feeds & Categories
global_clusters = []

for art in all_fetched_articles:
    matched = False
    for cluster in global_clusters:
        if is_same_story(art["clean_title"], cluster["clean_title"]):
            # Merge sources & links
            if not any(s["source"] == art["source"] for s in cluster["sources"]):
                cluster["sources"].append({"source": art["source"], "link": art["link"]})
            
            # PUNE (LOCAL) takes priority over national category
            if art["category"] == "PUNE (LOCAL)":
                cluster["category"] = "PUNE (LOCAL)"
                
            # Keep richer content
            if len(art["content"]) > len(cluster["content"]):
                cluster["content"] = art["content"]
                
            # Keep newest timestamp & time badge
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

# 3. Group deduplicated clusters back into categories for Gemini
category_raw_data = {}
all_clusters_map = {}

for cluster in global_clusters:
    tag = cluster["category"]
    if tag not in all_clusters_map:
        all_clusters_map[tag] = []
    all_clusters_map[tag].append(cluster)

for tag, clusters in all_clusters_map.items():
    # Sort by timestamp descending
    clusters.sort(key=lambda x: x["pub_ts"], reverse=True)
    category_raw_data[tag] = [
        {"id": i, "title": c["title"], "full_text": c["content"]}
        for i, c in enumerate(clusters[:10])
    ]

# 4. Batched API call
batch_results = {}

if client and category_raw_data:
    prompt = f"""You are an elite news editor. Summarize these raw articles for each provided category with absolute factual accuracy.

CATEGORIES AND RAW ARTICLES:
{json.dumps(category_raw_data)}

OUTPUT FORMAT:
Return a JSON object where each key is the category name, mapping to an array of summarized story objects:

{{
  "CATEGORY_NAME": [
    {{
      "headline": "Concise, Factual Headline",
      "takeaways": [
        "First complete sentence takeaway with details/metrics not in the headline.",
        "Second complete sentence takeaway providing essential background."
      ],
      "source_ids": [0]
    }}
  ]
}}

STRICT EDITORIAL RULES:
1. COMPLETE SENTENCES ONLY:
   - Every takeaway MUST be a full, grammatically complete sentence ending in a period.
   - NEVER end a sentence mid-word or with an ellipsis ('...').

2. ABSOLUTELY NO OPINIONS OR RECOMMENDATIONS: Exclude reviews, buying advice, editorials, and predictions.

3. "BUSINESS" CATEGORY: Include ONLY corporate acquisitions, mergers, business policies, earnings, and leadership news.

4. "SPORTS" CATEGORY DIVERSITY RULE: Select AT MOST 2 stories per sport. ALWAYS prefix the sport name (e.g., "[Cricket] ...", "[F1] ...").

5. NO HEADLINE REPETITION: Takeaways MUST NOT repeat or rephrase the headline.
"""

    candidate_models = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash-lite",
        "gemini-3.8-flash"
    ]

    for model_name in candidate_models:
        try:
            res = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                )
            )
            if res and res.text:
                batch_results = json.loads(res.text)
                print(f"✅ Successfully processed news using model: {model_name}")
                break
        except Exception as e:
            print(f"⚠️ Model '{model_name}' failed: {e}")

# 5. Construct HTML output
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
    <button class="tab-btn active" onclick="switchTab('today')">Today</button>
    <button class="tab-btn" onclick="switchTab('yesterday')">Yesterday</button>
    <button class="tab-btn" onclick="switchTab('older')">2-3 Days Ago</button>
  </div>
</header>
<div id="tab-today" class="tab-content active">
"""

tab_data = {"today": "", "yesterday": "", "older": ""}

for tag, raw_clusters in all_clusters_map.items():
    processed_groups = batch_results.get(tag, [])

    if not processed_groups:
        processed_groups = []
        for i, c in enumerate(raw_clusters[:10]):
            fallback_text = c["content"]
            processed_groups.append({
                "headline": c["title"],
                "takeaways": [fallback_text] if fallback_text else [c["title"]],
                "source_ids": [i]
            })

    cat_tab_html = {"today": "", "yesterday": "", "older": ""}
    for group in processed_groups:
        source_ids = group.get("source_ids", [])
        if not source_ids: continue
        matched_clusters = [raw_clusters[idx] for idx in source_ids if idx < len(raw_clusters)]
        if not matched_clusters: continue
        
        newest_cluster = max(matched_clusters, key=lambda x: x["pub_ts"])
        group_key = newest_cluster["group_key"]
        time_ago = newest_cluster["time_ago"]
        
        headline = group.get("headline") or newest_cluster["title"]
        headline = re.sub(r'^(Watch|LIVE|BREAKING):?\s*', '', headline, flags=re.IGNORECASE)
        takeaways = group.get("takeaways", [])
        valid_takeaways = [t.strip() for t in takeaways if t and isinstance(t, str)]
        if not valid_takeaways:
            valid_takeaways = [newest_cluster["content"]]
            
        takeaways_html = "".join([f"<li>{html.escape(t)}</li>" for t in valid_takeaways])
        
        # Merge sources
        sources_html = ""
        seen_sources = set()
        for c in matched_clusters:
            for s in c["sources"]:
                if s["source"] not in seen_sources:
                    sources_html += f'<a href="{s["link"]}" target="_blank" class="source-btn">{s["source"]} ↗</a>'
                    seen_sources.add(s["source"])
                
        card_html = f"""
        <div class="card">
          <details name="news-card">
            <summary>
              <span class="bullet">•</span>
              <span class="summary-text">{html.escape(headline)}</span>
              <span class="time-badge">{time_ago}</span>
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

    for gk in ["today", "yesterday", "older"]:
        if cat_tab_html[gk]:
            tab_data[gk] += f"<h2>{tag}</h2>" + cat_tab_html[gk]

html_out += tab_data["today"] if tab_data["today"] else "<div class='no-news'>No news published today yet.</div>"
html_out += '</div><div id="tab-yesterday" class="tab-content">'
html_out += tab_data["yesterday"] if tab_data["yesterday"] else "<div class='no-news'>No articles from yesterday.</div>"
html_out += '</div><div id="tab-older" class="tab-content">'
html_out += tab_data["older"] if tab_data["older"] else "<div class='no-news'>No articles from 2-3 days ago.</div>"

html_out += """
</div>
<script>
function switchTab(tabName) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + tabName).classList.add('active');
  event.target.classList.add('active');
}

document.querySelectorAll('details').forEach((el) => {
  el.addEventListener('toggle', (e) => {
    if (el.open) {
      document.querySelectorAll('details').forEach((otherEl) => {
        if (otherEl !== el) {
          otherEl.open = false;
        }
      });
    }
  });
});
</script>
</body>
</html>
"""

with open("index.html", "w") as f:
    f.write(html_out)
