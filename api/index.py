# Vercel serverless entrypoint.
# Vercel's @vercel/python runtime imports the `app` WSGI callable from this module.
import sys
from pathlib import Path

# Make the project root importable (app.py, squatter.py live one level up).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402  (WSGI app exposed to Vercel)
