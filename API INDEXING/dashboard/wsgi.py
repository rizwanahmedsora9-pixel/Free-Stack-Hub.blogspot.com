"""WSGI entry point (PythonAnywhere / gunicorn):  gunicorn wsgi:app"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from indexer.app import create_app  # noqa: E402

app = create_app()
