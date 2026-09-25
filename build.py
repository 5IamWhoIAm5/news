import feedparser, google.generativeai as genai, os, time, calendar, html, datetime

# Configure Gemini API
api_key = os.environ.get("GEMINI_API_KEY")
model = None
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Gemini init error: {e}")

# Feeds across all requested genres
FEEDS = {
    "ALL TOP STORIES": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "PUNE (LOCAL)": "https://news.google.com/rss/search?q=Pune&hl=en-IN&gl=IN&ceid=IN:en",
    "INDIA": "https://news.google.com/rss/search?q=India+News&hl=en-IN&gl=IN&ceid=IN:en",
    "WORLD": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "TECH": "https://feeds.feedburner.com/TechCrunch/",
    "FINANCE": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "AUTO": "https://www.autocarindia.com/rss/all",
    "SPORTS": "https://news.google.com/rss/search?q=Sports+India&hl=en-IN&gl=IN&ceid=IN:en",
    "CULTURE & MOVIES": "https://variety.com/feed/"
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def parse_time_info(entry):
    """Returns (group_key, time_ago_str, age_in_days)"""
    parsed_time = entry.get('published_parsed') or entry.get('updated_parsed')
    if not parsed_time:
        return ("today", "Today", 0)
    try:
        pub_ts = calendar.timegm(parsed_time)
        now_ts = time.time()
        diff = max(0, int(now_ts - pub_ts))
        
        days_old = diff / 86400.0
        
        if diff < 3600:
            time_ago = f"{max(1, diff // 60)}m ago"
        elif diff < 86400:
            time_ago = f"{diff // 3600}h ago"
        else:
            time_ago = f"{int(days_old)}d ago"
            
        if days_old < 1.0:
            return ("today", time_ago, days_old)
        elif days_old < 2.0:
            return ("yesterday", time_ago, days_old)
        elif days_old <= 3.5:
            return ("older", time_ago, days_old)
        else:
            return ("discard", time_ago, days_old) # Discard news older than 3 days
    except Exception:
        return ("today", "Today", 0)

# Build HTML Shell
html_out = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Micro News</title>
<style>
  :root {
    --bg: #090a0f;
    --card-bg: #13151c;
    --text: #e2e8f0;
    --text-muted: #94a3b8;
    --accent: #38bdf8;
    --border: #1e293b;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 12px; max-width: 600px; margin: 0 auto; padding-bottom: 50px; }
  header { padding: 12px 4px 8px; margin-bottom: 12px; }
  h1 { font-size: 20px; font-weight: 800; letter-spacing: -0.5px; color: #fff; margin-bottom: 12px; }
  
  /* Navigation Tabs */
  .tabs { display: flex; gap: 8px; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 16px; sticky: top; }
  .tab-btn { flex: 1; padding: 8px 12px; background: #13151c; border: 1px solid var(--border); color: var(--text-muted); font-size: 13px; font-weight: 700; border-radius: 8px; cursor: pointer; text-align: center; }
  .tab-btn.active { background: var(--accent); color: #000; border-color: var(--accent); }
  
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  h2 { color: var(--accent); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.2px; margin: 20px 4px 8px; }
  .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; overflow: hidden; }
  details { width: 100%; }
  summary { padding: 12px 14px; font-size: 14px; line-height: 1.45; font-weight: 500; cursor: pointer; list-style: none; color: #f1f5f9; display: flex; align-items: flex-start; gap: 8px; }
  summary::-webkit-details-marker { display: none; }
  .bullet { color: var(--accent); font-weight: bold; font-size: 16px; line-height: 1.2; flex-shrink: 0; }
  .time-badge { background: #1e293b; color: #94a3b8; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }
  .summary-text { flex-grow: 1; }
  .details-content { padding: 10px 14px 14px 26px; border-top: 1px solid rgba(255,255,255,0.05); font-size: 13px; color: var(--text-muted); line-height: 1.5; background: rgba(0,0,0,0.2); }
  .original-title { font-weight: 600; color: #cbd5e1; margin-bottom: 4px; }
  .source-btn { display: inline-block; margin-top: 10px; padding: 6px 12px; background: #1e293b; color: var(--accent); text-decoration: none; border-radius: 6px; font-size: 12px; font-weight: 600; }
  .no-news { color: var(--text-muted); font-size: 13px; padding: 12px; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>Micro News</h1>
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('today')">Today</button>
    <button class="tab-btn" onclick="switchTab('yesterday')">Yesterday</button>
    <button class="tab-btn" onclick="switchTab('older')">2-3 Days Ago</button>
  </div>
</header>

<div id="tab-today" class="tab-content active">
"""

# Containers for three time slots
tab_data = {"today": "", "yesterday": "", "older": ""}

for tag, url in FEEDS.items():
    feed = feedparser.parse(url, agent=USER_AGENT)
    
    cat_items = {"today": [], "yesterday": [], "older": []}
    
    for entry in feed.entries[:12]:
        group_key, time_ago, days_old = parse_time_info(entry)
        if group_key == "discard":
            continue # Automatically drops anything older than 3 days
            
        cat_items[group_key].append((entry, time_ago))

    for group_key in ["today", "yesterday", "older"]:
        items = cat_items[group_key]
        if items:
            section_html = f"<h2>{tag}</h2>"
            for entry, time_ago in items:
                summary = ""
                title = html.unescape(entry.get('title', ''))
                desc = html.unescape(entry.get('summary', entry.get('description', '')))
                link = entry.get('link', '#')
                
                clean_desc = desc.split('<')[0] if '<' in desc else desc
                if len(clean_desc) > 180: clean_desc = clean_desc[:180] + "..."

                if model:
                    try:
                        prompt = (
                            f"Convert this news item into EXACTLY ONE sentence under 12 words containing ONLY hard facts, numbers, prices, or core events. "
                            f"If culture/movies, IGNORE celebrity gossip or personal lives, ONLY report box office numbers, Oscars/Grammys, or major film releases. "
                            f"Zero fluff:\n{title} - {clean_desc}"
                        )
                        res = model.generate_content(prompt)
                        if res and res.text:
                            summary = res.text.strip()
                        time.sleep(0.8)
                    except Exception as e:
                        print(f"API Error: {e}")
                
                if not summary:
                    summary = title
                    
                section_html += f"""
                <div class="card">
                  <details>
                    <summary>
                      <span class="bullet">•</span>
                      <span class="summary-text">{summary}</span>
                      <span class="time-badge">{time_ago}</span>
                    </summary>
                    <div class="details-content">
                      <div class="original-title">{title}</div>
                      <div>{clean_desc}</div>
                      <a href="{link}" target="_blank" class="source-btn">Open Source ↗</a>
                    </div>
                  </details>
                </div>
                """
            tab_data[group_key] += section_html

# Assemble Page Body
html_out += tab_data["today"] if tab_data["today"] else "<div class='no-news'>No news published today yet.</div>"
html_out += '</div><div id="tab-yesterday" class="tab-content">'
html_out += tab_data["yesterday"] if tab_data["yesterday"] else "<div class='no-news'>No articles from yesterday.</div>"
html_out += '</div><div id="tab-older" class="tab-content">'
html_out += tab_data["older"] if tab_data["older"] else "<div class='no-news'>No articles from 2-3 days ago.</div>"

# Add JavaScript for switching tabs seamlessly
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
