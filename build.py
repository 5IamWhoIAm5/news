import feedparser, google.generativeai as genai, os, time, calendar, html, json, datetime

# Configure Gemini API with JSON Output Mode
api_key = os.environ.get("GEMINI_API_KEY")
model = None
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
    except Exception as e:
        print(f"Gemini init error: {e}")

now_ts = time.time()
build_time_str = datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %H:%M UTC")

# Multi-source feeds per category for deduplication
FEEDS = {
    "ALL TOP STORIES": [
        ("Google News", "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"),
        ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml")
    ],
    "PUNE (LOCAL)": [
        ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/cities/pune-news/rssfeed.xml"),
        ("Google News Pune", "https://news.google.com/rss/search?q=Pune&hl=en-IN&gl=IN&ceid=IN:en")
    ],
    "INDIA": [
        ("Indian Express", "https://indianexpress.com/section/india/feed/"),
        ("Google News India", "https://news.google.com/rss/search?q=India+News&hl=en-IN&gl=IN&ceid=IN:en")
    ],
    "WORLD": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("NYT", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml")
    ],
    "TECH": [
        ("TechCrunch", "https://feeds.feedburner.com/TechCrunch/"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index")
    ],
    "FINANCE": [
        ("NYT Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
        ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms")
    ],
    "AUTO": [
        ("Autocar India", "https://www.autocarindia.com/rss/all"),
        ("Motor Authority", "https://www.motorauthority.com/rss-feeds")
    ],
    "SPORTS": [
        ("Google Sports", "https://news.google.com/rss/search?q=Sports+India&hl=en-IN&gl=IN&ceid=IN:en"),
        ("ESPN", "https://www.espn.com/espn/rss/news")
    ],
    "CULTURE & MOVIES": [
        ("Variety", "https://variety.com/feed/"),
        ("Hollywood Reporter", "https://www.hollywoodreporter.com/feed/")
    ]
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

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

# HTML Layout Shell
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
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 12px; max-width: 600px; margin: 0 auto; padding-bottom: 50px; }}
  header {{ padding: 12px 4px 8px; margin-bottom: 12px; }}
  .header-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
  h1 {{ font-size: 20px; font-weight: 800; letter-spacing: -0.5px; color: #fff; }}
  .refresh-badge {{ font-size: 11px; color: var(--text-muted); background: #1a1d26; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--border); }}
  
  .tabs {{ display: flex; gap: 8px; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 16px; }}
  .tab-btn {{ flex: 1; padding: 8px 12px; background: #13151c; border: 1px solid var(--border); color: var(--text-muted); font-size: 13px; font-weight: 700; border-radius: 8px; cursor: pointer; text-align: center; }}
  .tab-btn.active {{ background: var(--accent); color: #000; border-color: var(--accent); }}
  
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  h2 {{ color: var(--accent); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.2px; margin: 20px 4px 8px; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; overflow: hidden; }}
  details {{ width: 100%; }}
  summary {{ padding: 12px 14px; font-size: 14px; line-height: 1.45; font-weight: 600; cursor: pointer; list-style: none; color: #f1f5f9; display: flex; align-items: flex-start; gap: 8px; }}
  summary::-webkit-details-marker {{ display: none; }}
  .bullet {{ color: var(--accent); font-weight: bold; font-size: 16px; line-height: 1.2; flex-shrink: 0; }}
  .time-badge {{ background: #1e293b; color: #94a3b8; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }}
  .summary-text {{ flex-grow: 1; }}
  
  .details-content {{ padding: 12px 14px 14px 26px; border-top: 1px solid rgba(255,255,255,0.05); font-size: 13px; color: #cbd5e1; line-height: 1.55; background: rgba(0,0,0,0.25); }}
  .gist-text {{ margin-bottom: 10px; font-weight: 400; }}
  .sources-container {{ margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
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

    # 1. Fetch raw items from all feeds in category
    for source_name, feed_url in feed_list:
        parsed = feedparser.parse(feed_url, agent=USER_AGENT)
        for entry in parsed.entries[:6]:
            group_key, time_ago, days_old, pub_ts = parse_time_info(entry.get('published_parsed') or entry.get('updated_parsed'))
            if group_key == "discard":
                continue
                
            title = html.unescape(entry.get('title', ''))
            desc = html.unescape(entry.get('summary', entry.get('description', '')))
            clean_desc = desc.split('<')[0] if '<' in desc else desc
            link = entry.get('link', '#')
            
            raw_articles.append({
                "source": source_name,
                "title": title,
                "desc": clean_desc[:250],
                "link": link,
                "pub_ts": pub_ts,
                "group_key": group_key,
                "time_ago": time_ago
            })

    if not raw_articles:
        continue

    # 2. Process & Deduplicate using Gemini
    processed_groups = []
    
    if model:
        try:
            # Prepare minimal JSON list for AI processing
            input_items = [{"id": i, "title": a["title"], "desc": a["desc"], "source": a["source"]} for i, a in enumerate(raw_articles[:12])]
            
            prompt = (
                f"You are a news deduplication and summarization engine. Here is a JSON array of news items for category '{tag}':\n"
                f"{json.dumps(input_items)}\n\n"
                f"Task:\n"
                f"1. Group articles that report on the EXACT same news event or topic into a single story.\n"
                f"2. For each story, provide:\n"
                f"   - 'micro_headline': STRICT 10-12 word factual sentence. ZERO clickbait, hooks, or fluff. ONLY hard numbers, entities, actions.\n"
                f"   - 'detailed_gist': A thorough 2-4 sentence summary containing all key facts, context, figures, and background so the reader does NOT need to click the source link.\n"
                f"   - 'source_ids': Array of integer IDs from input list belonging to this story.\n"
                f"Return JSON array of story objects."
            )
            
            res = model.generate_content(prompt)
            if res and res.text:
                processed_groups = json.loads(res.text)
            time.sleep(1)
        except Exception as e:
            print(f"Gemini API Error for {tag}: {e}")

    # Fallback if AI grouping fails
    if not processed_groups:
        processed_groups = [{
            "micro_headline": a["title"],
            "detailed_gist": a["desc"],
            "source_ids": [i]
        } for i, a in enumerate(raw_articles[:8])]

    # 3. Render Cards into Time Tabs
    cat_tab_html = {"today": "", "yesterday": "", "older": ""}

    for group in processed_groups:
        source_ids = group.get("source_ids", [])
        if not source_ids:
            continue
            
        matched_articles = [raw_articles[idx] for idx in source_ids if idx < len(raw_articles)]
        if not matched_articles:
            continue

        # Use the newest timestamp among grouped articles
        newest_article = max(matched_articles, key=lambda x: x["pub_ts"])
        group_key = newest_article["group_key"]
        time_ago = newest_article["time_ago"]

        headline = group.get("micro_headline", newest_article["title"])
        gist = group.get("detailed_gist", newest_article["desc"])

        # Render unique source buttons
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
              <span class="summary-text">{headline}</span>
              <span class="time-badge">{time_ago}</span>
            </summary>
            <div class="details-content">
              <div class="gist-text">{gist}</div>
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

# Assemble Document
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
