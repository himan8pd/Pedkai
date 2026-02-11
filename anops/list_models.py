"""
Script to list available Gemini models.
"""

from google import genai
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.config import get_settings

settings = get_settings()

if settings.gemini_api_key:
    client = genai.Client(api_key=settings.gemini_api_key)
    print("Listing models...")
    for m in client.models.list():
        # In the new SDK, we can check capabilities or just list all
        print(f"- {m.name}")
else:
    print("GEMINI_API_KEY not set.")
