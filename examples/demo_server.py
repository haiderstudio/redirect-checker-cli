#!/usr/bin/env python3
"""Demo server for the redirect-checker-cli examples.

Serves a small set of fixed redirect routes on localhost so the
bundled examples run with real HTTP, offline. Run from the repo root:

    python3 examples/demo_server.py 8123

Routes:
    /ok     -> 200
    /old    -> 301 to /new, /new -> 200
    /a      -> 301 to /b, /b -> 302 to /c, /c -> 200
    /loop1  -> 302 to /loop2, /loop2 -> 302 to /loop1 (a loop)
    /long1  -> 302 to /long2 ... /long11 -> 302 to /long12, /long12 -> 200
    /gone   -> 404
    /self   -> 302 to itself
    /rel    -> 302 with a relative Location (/ok)

Standard library only.
"""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTES = {
    "/ok": (200, None, b"ok\n"),
    "/new": (200, None, b"new page\n"),
    "/c": (200, None, b"final page\n"),
    "/old": (301, "/new", b""),
    "/a": (301, "/b", b""),
    "/b": (302, "/c", b""),
    "/loop1": (302, "/loop2", b""),
    "/loop2": (302, "/loop1", b""),
    "/gone": (404, None, b"not here\n"),
    "/self": (302, "/self", b""),
    "/rel": (302, "/ok", b""),
}
for number in range(1, 12):
    ROUTES["/long%d" % number] = (302, "/long%d" % (number + 1), b"")
ROUTES["/long12"] = (200, None, b"end of a long chain\n")


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, location, body = ROUTES.get(
            self.path, (404, None, b"not here\n"))
        self.send_response(status)
        if location is not None:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the demo output clean
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    print("demo server on http://127.0.0.1:%d (Ctrl-C to stop)" % port)
    server.serve_forever()


if __name__ == "__main__":
    main()
