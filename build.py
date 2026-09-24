import feedparser, google.generativeai as genai, os

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-2.5-flash')

FEEDS = {
    "WORLD": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "TECH": "https://techcrunch.com/feed/",
    "FINANCE": "https://search.cnbc.com/rs/search/combinedrender?source=cnbcnews&id=10000664&tab=news",
    "AUTO": "https://www.autoblog.com/rss.xml",
    "SCIENCE": "https://www.sciencedaily.com/rss/all.xml",
    "SPORTS": "https://www.espn.com/espn/rss/news"
}

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
    feed = feedparser.parse(url)
    for entry in feed.entries[:3]:
        prompt = f"Convert this story into EXACTLY ONE sentence under 12 words containing ONLY hard facts, prices, stats, or key events. Zero fluff/hooks:\n{entry.title} - {entry.description}"
        try:
            summary = model.generate_content(prompt).text.strip()
            html += f"<p>• {summary}</p>"
        except Exception:
            pass

html += "</body></html>"

with open("index.html", "w") as f:
    f.write(html)
