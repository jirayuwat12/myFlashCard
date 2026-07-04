import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("Flashcards at http://localhost:8000")
    ThreadingHTTPServer(("", 8000), SimpleHTTPRequestHandler).serve_forever()
