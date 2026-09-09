"""
Project TEMPO: Live Interactive Dashboard Server.
Launches a lightweight local HTTP server and automatically opens the visualization in your browser.
"""

import http.server
import socketserver
import webbrowser
import os
import sys

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

def main():
    os.chdir(DIRECTORY)
    # Find available port if 8080 is taken
    global PORT
    while PORT < 8100:
        try:
            with socketserver.TCPServer(("", PORT), Handler) as httpd:
                url = f"http://localhost:{PORT}/index.html"
                print("=" * 70)
                print(f"  PROJECT TEMPO: LIVE VISUALIZATION DASHBOARD")
                print(f"  Running on: {url}")
                print("  Press Ctrl+C to stop the server.")
                print("=" * 70)
                webbrowser.open(url)
                httpd.serve_forever()
                break
        except OSError:
            PORT += 1

if __name__ == "__main__":
    main()
