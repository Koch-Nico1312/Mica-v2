from __future__ import annotations

import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler


if __name__ == "__main__":
    os.chdir(os.getenv("WEB_ROOT", "/app/web_ui"))
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8088"))), SimpleHTTPRequestHandler).serve_forever()
