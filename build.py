import feedparser, os, time, calendar, html, json, datetime, re, requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

# Configure Gemini API using modern google.genai SDK
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

def is_unwanted_article(title, content):
    """Filters out live blogs, opinion pieces, reviews, and personal recommendations."""
    combined = f"{title} {content}".lower()
    unwanted_patterns = [
        # Live blogs / intraday noise
        "stock market live", "sensex", "nifty", "trade flat", "opening bell",
        "market live updates", "rupee opens", "equity benchmarks", "stocks to watch",
        # Opinion & recommendations
        "opinion:", "editorial:", "my take:", "buying guide", "should you buy",
        "top 10", "best deals", "hands-on review", "our verdict", "why you should",
        "perspective:", "viewpoint:", "review:"
    ]
    return any(p in combined for p in unwanted_patterns)

def get_full_article_content(entry, url):
    if hasattr(entry, 'content') and entry.content:
        for c in entry.content:
            val = clean_text(c.get('value', ''))
            if len(val) > 250:
                return val[:2500]

    summary = clean_text(entry.get('summary', entry.get('description', '')))
    
    if url and url != '#' and len(summary) < 400:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                resp.encoding = 'utf-8'
                soup = BeautifulSoup(resp.text, 'html.parser')
                for s in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form']):
                    s.decompose()
                paragraphs = soup.find_all('p')
                p_texts = [clean_text(p.get_text()) for p in paragraphs if len(clean_text(p.get_text())) > 30]
                scraped_text = " ".join(p_texts[:8])
                if len(scraped_text) > len(summary):
                    return scraped_text[:2500]
        except Exception:
            pass
    return summary

def parse_time_info(parsed_time):
    """Uses IST calendar date boundaries so local news isn't pushed into 'Yesterday' due to UTC offsets."""
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

        # Compare calendar dates in IST
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

# 1. Fetch articles across categories
category_raw_data = {}
all_articles_map = {}

for tag, feed_list in FEEDS.items():
    raw_articles = []
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
                
            raw_articles.append({
                "source": source_name,
                "title": raw_title,
                "content": full_content,
                "link": link,
                "pub_ts": pub_ts,
                "group_key": group_key,
                "time_ago": time_ago
            })
    if raw_articles:
        all_articles_map[tag] = raw_articles
        category_raw_data[tag] = [
            {"id": i, "title": a["title"], "full_text": a["content"]}
            for i, a in enumerate(raw_articles[:12])
        ]

# 2. Batched API call with strict business focus & sports topic balancing
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
        "First factual takeaway with details/metrics not in the headline.",
        "Second factual takeaway providing essential background."
      ],
      "source_ids": [0, 1]
    }}
  ]
}}

STRICT EDITORIAL RULES:
1. ABSOLUTELY NO OPINIONS OR RECOMMENDATIONS: Exclude reviews, buying advice, personal opinions, editorials, and predictions. State ONLY verifiable, established facts.

2. "BUSINESS" CATEGORY REQUIREMENTS:
   - ONLY include company acquisitions, mergers, corporate policies, quarterly financial earnings, leadership changes, and strategic business deals.
   - EXCLUDE general politics, air crashes, or stock market ticker recommendations.

3. "SPORTS" CATEGORY DIVERSITY RULE (CRITICAL):
   - Sports news is vast. You MUST NOT allow one sport (like Cricket or Football) to dominate.
   - Select AT MOST 2 stories per sport (e.g. max 2 Cricket, max 2 Football, max 1 Tennis, max 1 Chess, max 1 F1).
   - ALWAYS prefix the sport name to the headline (e.g., "[Cricket] India Defeats Australia in 3rd Test", "[Chess] Gukesh Advances to Candidates Final", "[F1] Ferrari Announces New Engine Specs").
   - Explicitly mention tournament names, team names, and country context so identity is never ambiguous.

4. "PUNE (LOCAL)" CATEGORY:
   - Include only events taking place in Pune city, PCMC, or local Pune district.

5. NO HEADLINE REPETITION: Takeaways MUST NOT repeat or rephrase the headline. Provide new figures, context, or implications.

6. DEDUPLICATION: Combine articles covering the exact same event into ONE object with multiple source_ids.
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

# 3. Construct HTML output
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

for tag, raw_articles in all_articles_map.items():
    processed_groups = batch_results.get(tag, [])

    if not processed_groups:
        processed_groups = []
        for i, a in enumerate(raw_articles[:10]):
            fallback_text = a["content"][:220] + "..." if len(a["content"]) > 220 else a["content"]
            processed_groups.append({
                "headline": a["title"],
                "takeaways": [fallback_text] if fallback_text else [a["title"]],
                "source_ids": [i]
            })

    cat_tab_html = {"today": "", "yesterday": "", "older": ""}
    for group in processed_groups:
        source_ids = group.get("source_ids", [])
        if not source_ids: continue
        matched_articles = [raw_articles[idx] for idx in source_ids if idx < len(raw_articles)]
        if not matched_articles: continue
        
        newest_article = max(matched_articles, key=lambda x: x["pub_ts"])
        group_key = newest_article["group_key"]
        time_ago = newest_article["time_ago"]
        
        headline = group.get("headline") or newest_article["title"]
        headline = re.sub(r'^(Watch|LIVE|BREAKING):?\s*', '', headline, flags=re.IGNORECASE)
        takeaways = group.get("takeaways", [])
        valid_takeaways = [t.strip() for t in takeaways if t and isinstance(t, str)]
        if not valid_takeaways:
            valid_takeaways = [newest_article["content"]]
            
        takeaways_html = "".join([f"<li>{html.escape(t)}</li>" for t in valid_takeaways])
        sources_html = ""
        seen_sources = set()
        for a in matched_articles:
            if a["source"] not in seen_sources:
                sources_html += f'<a href="{a["link"]}" target="_blank" class="source-btn">{a["source"]} ↗</a>'
                seen_sources.add(a["source"])
                
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

// Auto-close open cards when a new card is opened
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
