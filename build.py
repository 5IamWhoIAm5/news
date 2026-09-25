import feedparser, google.generativeai as genai, os, time, calendar, html, json, datetime, re, requests
from bs4 import BeautifulSoup

# Configure Gemini API
api_key = os.environ.get("GEMINI_API_KEY")
model = None
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.1
            }
        )
    except Exception as e:
        print(f"Gemini init error: {e}")

now_ts = time.time()
build_time_str = datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %H:%M UTC")

FEEDS = {
    "ALL TOP STORIES": [
        ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("BBC", "https://feeds.bbci.co.uk/news/rss.xml"),
        ("Indian Express", "https://indianexpress.com/feed/")
    ],
    "PUNE (LOCAL)": [
        ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/cities/pune-news/rssfeed.xml"),
        ("Indian Express Pune", "https://indianexpress.com/section/cities/pune/feed/")
    ],
    "INDIA": [
        ("NDTV India", "https://feeds.feedburner.com/ndtvnews-india-news"),
        ("Indian Express", "https://indianexpress.com/section/india/feed/"),
        ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms")
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
    "FINANCE": [
        ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
        ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml")
    ],
    "AUTO": [
        ("Autocar India", "https://www.autocarindia.com/rss/all"),
        ("MotorOctane", "https://motoroctane.com/feed")
    ],
    "SPORTS": [
        ("ESPN Cricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"),
        ("NDTV Sports", "https://feeds.feedburner.com/ndtvsports-latest")
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

def is_junk_live_blog(title, content):
    t_lower = title.lower()
    junk_patterns = [
        "stock market live", "sensex", "nifty", "trade flat", "traded flat",
        "opening bell", "share market live", "market live updates",
        "rupee opens", "rupee open", "equity benchmarks", "stocks to watch",
        "gainers and losers", "market opening", "bse sensex", "nifty 50"
    ]
    if any(k in t_lower for k in junk_patterns):
        return True
    return False

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
    if not parsed_time:
        return ("today", "Today", 0, now_ts)
    try:
        pub_ts = calendar.timegm(parsed_time)
        diff = max(0, int(now_ts - pub_ts))
        days_old = diff / 86400.0
        
        if diff < 3600:
            time_ago = f"{max(1, diff // 60)}m ago"
        elif diff < 86400:
            time_ago = f"{diff // 3600}h ago"
        else:
            time_ago = f"{int(days_old)}d ago"
            
        if days_old < 1.0:
            return ("today", time_ago, days_old, pub_ts)
        elif days_old < 2.0:
            return ("yesterday", time_ago, days_old, pub_ts)
        elif days_old <= 3.5:
            return ("older", time_ago, days_old, pub_ts)
        else:
            return ("discard", time_ago, days_old, pub_ts)
    except Exception:
        return ("today", "Today", 0, now_ts)

# HTML Layout Setup
html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Micro News</title>
<style>
  :root {{
    --bg: #090a0f;
    --card-bg: #13151c;
    --text: #e2e8f0;
    --text-muted: #94a3b8;
    --accent: #38bdf8;
    --border: #1e293b;
  }}
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
  .takeaways-list {{ margin: 0 0 12px 0; padding-left: 18px; list-style-type: disc; }}
  .takeaways-list li {{ margin-bottom: 8px; color: #e2e8f0; font-size: 13px; line-height: 1.5; }}
  .sources-container {{ margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
  .sources-label {{ font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-right: 4px; }}
  .source-btn {{ display: inline-block; padding: 4px 8px; background: #1e293b; color: var(--accent); text-decoration: none; border-radius: 4px; font-size: 11px; font-weight: 600; }}
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

for tag, feed_list in FEEDS.items():
    raw_articles = []

    for source_name, feed_url in feed_list:
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries[:6]:
            group_key, time_ago, days_old, pub_ts = parse_time_info(entry.get('published_parsed') or entry.get('updated_parsed'))
            if group_key == "discard":
                continue
                
            raw_title = clean_text(entry.get('title', ''))
            link = entry.get('link', '#')
            
            full_content = get_full_article_content(entry, link)

            if is_junk_live_blog(raw_title, full_content):
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

    if not raw_articles:
        continue

    processed_groups = []
    
    if model:
        try:
            input_items = [
                {"id": i, "title": a["title"], "full_text": a["content"]}
                for i, a in enumerate(raw_articles[:10])
            ]
            
            prompt = (
                f"You are a ruthless editor. Analyze these news items for category '{tag}':\n{json.dumps(input_items)}\n\n"
                f"STRICT RULES:\n"
                f"1. EXTREME BREVITY (CRITICAL): Each string in the 'takeaways' array MUST be a single, direct sentence (maximum 25 words). Break long articles into 2 to 4 separate, short bullet points. Strip all adjectives, quotes, and narrative fluff. Only output hard facts, numbers, and direct actions.\n"
                f"2. DEDUPLICATION: Merge identical stories into 1 object.\n"
                f"3. ZERO META: Never say 'Sources say', 'Watch:', or name journalists/news agencies (like AFP or BBC).\n"
                f"4. ENTITY CONTEXT: Briefly define who/what an entity is within the short sentence (e.g., '63-year-old UP businessman Vineet Manocha').\n"
                f"5. NO CLIFFHANGERS: State the final outcome directly. Do not end on unresolved statements.\n"
                f"6. OUTPUT FORMAT: JSON array of objects with keys: 'headline', 'takeaways' (array of 1-4 short bullet strings), 'source_ids' (array of integer IDs).\n"
            )
            
            res = model.generate_content(prompt)
            if res and res.text:
                resp_text = res.text.strip()
                if resp_text.startswith("```"):
                    resp_text = re.sub(r"^```[a-z]*\n?", "", resp_text)
                    resp_text = re.sub(r"\n?```$", "", resp_text)
                processed_groups = json.loads(resp_text)
            time.sleep(1)
        except Exception as e:
            print(f"Gemini API Error for {tag}: {e}")

    if not processed_groups:
        processed_groups = [{
            "headline": a["title"],
            "takeaways": [a["content"][:100] + "..."] if a["content"] else [a["title"]],
            "source_ids": [i]
        } for i, a in enumerate(raw_articles[:8])]

    cat_tab_html = {"today": "", "yesterday": "", "older": ""}

    for group in processed_groups:
        source_ids = group.get("source_ids", [])
        if not source_ids:
            continue
            
        matched_articles = [raw_articles[idx] for idx in source_ids if idx < len(raw_articles)]
        if not matched_articles:
            continue

        newest_article = max(matched_articles, key=lambda x: x["pub_ts"])
        group_key = newest_article["group_key"]
        time_ago = newest_article["time_ago"]

        headline = group.get("headline") or newest_article["title"]
        headline = re.sub(r'^(Watch|LIVE|BREAKING):?\s*', '', headline, flags=re.IGNORECASE)
        
        takeaways = group.get("takeaways", [])

        valid_takeaways = [t.strip() for t in takeaways if t and isinstance(t, str)]
        if not valid_takeaways:
            valid_takeaways = [newest_article["content"][:100] + "..."]

        takeaways_html = "".join([f"<li>{html.escape(t)}</li>" for t in valid_takeaways])

        sources_html = ""
        seen_sources = set()
        for a in matched_articles:
            if a["source"] not in seen_sources:
                sources_html += f'<a href="{a["link"]}" target="_blank" class="source-btn">{a["source"]} ↗</a>'
                seen_sources.add(a["source"])

        card_html = f"""
        <div class="card">
          <details>
            <summary>
              <span class="bullet">•</span>
              <span class="summary-text">{html.escape(headline)}</span>
              <span class="time-badge">{time_ago}</span>
            </summary>
            <div class="details-content">
              <ul class="takeaways-list">
                {takeaways_html}
              </ul>
              <div class="sources-container">
                <span class="sources-label">Sources:</span>
                {sources_html}
              </div>
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
</script>
</body>
</html>
"""

with open("index.html", "w") as f:
    f.write(html_out)
