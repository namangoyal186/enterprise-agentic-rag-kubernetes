"""
Vercel Serverless Entrypoint for FastAPI.
"""
import sys
import os

# Ensure root directory is on the Python module search path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
