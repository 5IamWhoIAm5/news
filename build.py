import feedparser, google.generativeai as genai, os

# Configure Gemini Model
api_key = os.environ.get("GEMINI_API_KEY")
model = None
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Gemini init error: {e}")

# Working RSS Feeds across all genres
FEEDS = {
    "WORLD": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "TECH": "https://techcrunch.com/feed/",
    "FINANCE": "https://search.cnbc.com/rs/search/combinedrender?source=cnbcnews&id=10000664&tab=news",
    "AUTO": "https://www.autoblog.com/rss.xml",
    "SCIENCE": "https://www.sciencedaily.com/rss/all.xml",
    "SPORTS": "https://www.espn.com/espn/rss/news"
}

# Browser header to prevent HTTP 403 blocks from news servers
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

html = """<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { background:#0a0a0a; color:#e0e0e0; font-family:sans-serif; padding:16px; max-width:600px; margin:0 auto; }
  h2 { color:#4da6ff; border-bottom:1px solid #333; margin-top:24px; font-size:14px; text-transform:uppercase; letter-spacing:1px; }
  p { font-size:14px; line-height:1.5; margin:10px 0; padding-bottom:8px; border-bottom:1px solid #1e1e1e; }
</style>
</head><body><h1 style="font-size:20px;">Micro News</h1>"""

for tag, url in FEEDS.items():
    html += f"<h2>{tag}</h2>"
    feed = feedparser.parse(url, agent=USER_AGENT)
    
    entries = feed.entries[:3]
    if not entries:
        html += "<p>• Feed unavailable at the moment.</p>"
        continue
        
    for entry in entries:
        summary = ""
        title = entry.get('title', '')
        desc = entry.get('summary', entry.get('description', ''))
        
        if model:
            try:
                prompt = f"Convert this story into EXACTLY ONE sentence under 12 words containing ONLY hard facts, prices, stats, or key events. Zero fluff or hooks:\n{title} - {desc}"
                res = model.generate_content(prompt)
                if res and res.text:
                    summary = res.text.strip()
            except Exception as e:
                print(f"API Error: {e}")
        
        # Fallback to headline if API call fails
        if not summary:
            summary = title
            
        html += f"<p>• {summary}</p>"

html += "</body></html>"

with open("index.html", "w") as f:
    f.write(html)
