import feedparser, google.generativeai as genai, os, time, html

# Configure Gemini API
api_key = os.environ.get("GEMINI_API_KEY")
model = None
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Gemini init error: {e}")

# Feeds including Local Pune, India, World, Tech, Finance, Auto, Sports, and Mild Culture
FEEDS = {
    "PUNE (LOCAL)": "https://www.hindustantimes.com/feeds/rss/cities/pune-news/rssfeed.xml",
    "INDIA": "https://indianexpress.com/section/india/feed/",
    "WORLD": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "TECH": "https://feeds.feedburner.com/TechCrunch/",
    "FINANCE": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "AUTO": "https://www.motorauthority.com/rss-feeds",
    "SPORTS": "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml",
    "CULTURE & MOVIES": "https://variety.com/feed/"
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

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
  header { padding: 16px 4px 12px; border-bottom: 1px solid var(--border); margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
  h1 { font-size: 20px; font-weight: 800; letter-spacing: -0.5px; color: #fff; }
  .tag-badge { background: #1e293b; color: var(--accent); font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 12px; text-transform: uppercase; }
  h2 { color: var(--accent); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.2px; margin: 24px 4px 10px; }
  .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; overflow: hidden; }
  details { width: 100%; }
  summary { padding: 12px 14px; font-size: 14px; line-height: 1.45; font-weight: 500; cursor: pointer; list-style: none; color: #f1f5f9; display: flex; gap: 8px; }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: "•"; color: var(--accent); font-weight: bold; font-size: 16px; line-height: 1; flex-shrink: 0; }
  .details-content { padding: 10px 14px 14px 26px; border-top: 1px solid rgba(255,255,255,0.05); font-size: 13px; color: var(--text-muted); line-height: 1.5; background: rgba(0,0,0,0.2); }
  .original-title { font-weight: 600; color: #cbd5e1; margin-bottom: 4px; }
  .source-btn { display: inline-block; margin-top: 10px; padding: 6px 12px; background: #1e293b; color: var(--accent); text-decoration: none; border-radius: 6px; font-size: 12px; font-weight: 600; }
  .source-btn:active { background: var(--accent); color: #000; }
</style>
</head>
<body>
<header>
  <h1>Micro News</h1>
  <span class="tag-badge">Live</span>
</header>
"""

for tag, url in FEEDS.items():
    html_out += f"<h2>{tag}</h2>"
    feed = feedparser.parse(url, agent=USER_AGENT)
    
    entries = feed.entries[:8]  # Bumping limit to 8 per category for heavy news days
    if not entries:
        html_out += "<div class='card'><summary>Feed temporarily offline.</summary></div>"
        continue
        
    for entry in entries:
        summary = ""
        title = html.unescape(entry.get('title', ''))
        desc = html.unescape(entry.get('summary', entry.get('description', '')))
        link = entry.get('link', '#')
        
        # Strip raw HTML tags from description
        clean_desc = desc.split('<')[0] if '<' in desc else desc
        if len(clean_desc) > 180: clean_desc = clean_desc[:180] + "..."

        if model:
            try:
                # Custom prompt instructing AI to strip celeb gossip and stick to core facts
                prompt = (
                    f"Convert this news item into EXACTLY ONE sentence under 12 words containing ONLY hard facts, numbers, prices, or core events. "
                    f"If this is culture/movies, strictly IGNORE celebrity gossip or personal lives, and ONLY report box office numbers, Oscars/Grammys, or major film releases. "
                    f"Zero fluff:\n{title} - {clean_desc}"
                )
                res = model.generate_content(prompt)
                if res and res.text:
                    summary = res.text.strip()
                time.sleep(1) # Prevent rate limiting
            except Exception as e:
                print(f"API Error: {e}")
        
        if not summary:
            summary = title
            
        html_out += f"""
        <div class="card">
          <details>
            <summary>{summary}</summary>
            <div class="details-content">
              <div class="original-title">{title}</div>
              <div>{clean_desc}</div>
              <a href="{link}" target="_blank" class="source-btn">Open Source ↗</a>
            </div>
          </details>
        </div>
        """

html_out += "</body></html>"

with open("index.html", "w") as f:
    f.write(html_out)
