import os
import google.generativeai as genai

# 1. Check if the key is actually loading in this specific terminal/environment
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("❌ ERROR: API Key is missing. Your environment variable is not loading.")
    exit()
else:
    print("✅ API Key found in environment.")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-1.5-flash')

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

print("⏳ Sending test request to Gemini...")
try:
    res = model.generate_content(
        'Return exactly this JSON: [{"test": "success"}]',
        safety_settings=safety_settings,
        generation_config={"response_mime_type": "application/json"}
    )
    print("✅ API CONNECTION SUCCESSFUL:")
    print(res.text)
except Exception as e:
    print(f"❌ API ERROR CRASH: {e}")
