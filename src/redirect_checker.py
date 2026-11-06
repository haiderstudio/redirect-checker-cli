#!/usr/bin/env python3
"""Check URL redirect chains.

One job: take a list of URLs, follow each redirect chain, and report
the final destination, the chain length, and any loop or chain that is
too long. Report-only — it changes nothing on any site.

Python standard library only (urllib). No third-party packages.
"""

import argparse
import contextlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "1.0.0"
DEFAULT_MAX_REDIRECTS = 10
DEFAULT_TIMEOUT = 10
USER_AGENT = "redirect-checker-cli/1.0"

REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that never follows — it returns the 3xx
    response so the caller can record the hop and decide itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_fetcher(url, timeout):
    """Fetch one URL without following redirects.

    Returns (status, location) where location is the Location header
    value or None. Raises URLError / HTTPError for transport problems.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_NoRedirectHandler)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Location")
    except urllib.error.HTTPError as error:
        # A 3xx/4xx/5xx response still arrives here when the opener
        # refuses to follow it; treat it as a normal hop.
        return error.code, error.headers.get("Location")


def check_url(url, max_redirects=DEFAULT_MAX_REDIRECTS,
              timeout=DEFAULT_TIMEOUT, fetcher=None):
    """Follow one URL's redirect chain.

    Returns a dict with keys: url, hops (list of {"url", "status"}),
    final_url, final_status, outcome, detail.

    outcome is one of: OK, CHAIN, LOOP, LONG, FAIL, ERROR.
    - OK: no redirect, final status 2xx.
    - CHAIN: one or more redirects, final status 2xx.
    - LOOP: a URL repeats in the chain.
    - LONG: more redirects than max_redirects.
    - FAIL: the final status is 4xx or 5xx.
    - ERROR: the URL could not be fetched at all.
    """
    fetch = fetcher or _default_fetcher
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {
            "url": url,
            "hops": [],
            "final_url": url,
            "final_status": None,
            "outcome": "ERROR",
            "detail": "not an http(s) URL",
        }

    hops = []
    seen = set()
    current = url
    while True:
        if current in seen:
            return {
                "url": url,
                "hops": hops,
                "final_url": current,
                "final_status": hops[-1]["status"] if hops else None,
                "outcome": "LOOP",
                "detail": "loop after %d redirect(s)" % len(hops),
            }
        seen.add(current)
        try:
            status, location = fetch(current, timeout)
        except (urllib.error.URLError, OSError, ValueError) as error:
            return {
                "url": url,
                "hops": hops,
                "final_url": current,
                "final_status": None,
                "outcome": "ERROR",
                "detail": str(error) or error.__class__.__name__,
            }
        hops.append({"url": current, "status": status})
        if status in REDIRECT_STATUSES:
            if not location:
                return {
                    "url": url,
                    "hops": hops,
                    "final_url": current,
                    "final_status": status,
                    "outcome": "FAIL",
                    "detail": "redirect with no Location header",
                }
            if len(hops) - 1 >= max_redirects:
                nxt = urllib.parse.urljoin(current, location)
                return {
                    "url": url,
                    "hops": hops,
                    "final_url": nxt,
                    "final_status": status,
                    "outcome": "LONG",
                    "detail": "more than %d redirect(s)" % max_redirects,
                }
            current = urllib.parse.urljoin(current, location)
            continue
        if 200 <= status < 300:
            outcome = "OK" if len(hops) == 1 else "CHAIN"
            return {
                "url": url,
                "hops": hops,
                "final_url": current,
                "final_status": status,
                "outcome": outcome,
                "detail": "%d redirect(s)" % (len(hops) - 1),
            }
        return {
            "url": url,
            "hops": hops,
            "final_url": current,
            "final_status": status,
            "outcome": "FAIL",
            "detail": "final status %d" % status,
        }


def read_urls_from_file(path):
    """Read one URL per line; blank lines and # comments are skipped."""
    urls = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def collect_urls(args, stdin_text=None):
    """Gather the URLs to check from args, --file, or --stdin."""
    urls = list(args.urls)
    if args.file:
        urls.extend(read_urls_from_file(args.file))
    if args.stdin:
        text = stdin_text if stdin_text is not None else sys.stdin.read()
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def format_result(result):
    """One plain-text line for one checked URL."""
    outcome = result["outcome"]
    url = result["url"]
    if outcome in ("OK", "CHAIN"):
        codes = ", ".join(str(h["status"]) for h in result["hops"][:-1])
        if codes:
            hops_text = "%d redirect(s): %s" % (len(result["hops"]) - 1, codes)
        else:
            hops_text = "0 redirects"
        return "%-7s %s -> %s [%s] (%s)" % (
            outcome, url, result["final_url"],
            result["final_status"], hops_text)
    if outcome == "LOOP":
        return "%-7s %s -> %s (%s)" % (
            outcome, url, result["final_url"], result["detail"])
    if outcome == "LONG":
        return "%-7s %s -> %s (%s)" % (
            outcome, url, result["final_url"], result["detail"])
    if outcome == "FAIL":
        return "%-7s %s -> %s (%s)" % (
            outcome, url, result["final_url"], result["detail"])
    return "%-7s %s (%s)" % (outcome, url, result["detail"])


def build_parser():
    parser = argparse.ArgumentParser(
        prog="redirect_checker",
        description="Check URL redirect chains, flag loops and long chains.")
    parser.add_argument("urls", nargs="*", help="URLs to check")
    parser.add_argument("--file", metavar="FILE",
                        help="read URLs, one per line, from FILE")
    parser.add_argument("--stdin", action="store_true",
                        help="read URLs, one per line, from standard input")
    parser.add_argument("--max-redirects", type=int,
                        default=DEFAULT_MAX_REDIRECTS, metavar="N",
                        help="fail a chain longer than N redirects "
                             "(default %d)" % DEFAULT_MAX_REDIRECTS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        metavar="SECONDS",
                        help="seconds to wait per request (default %d)"
                             % DEFAULT_TIMEOUT)
    parser.add_argument("--json", action="store_true",
                        help="print results as JSON instead of text")
    parser.add_argument("--version", action="version",
                        version="redirect-checker-cli " + VERSION)
    return parser


def run(argv=None, stdin_text=None, stdout=None, stderr=None):
    """Run the CLI. Returns the exit code: 0 all ok, 1 any problem,
    2 usage error."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    parser = build_parser()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            args = parser.parse_args(argv)
        except SystemExit as exit_error:
            return exit_error.code if isinstance(exit_error.code, int) else 2
    if args.max_redirects < 0:
        print("error: --max-redirects must be 0 or more", file=err)
        return 2
    if args.timeout <= 0:
        print("error: --timeout must be more than 0", file=err)
        return 2
    try:
        urls = collect_urls(args, stdin_text=stdin_text)
    except OSError as error:
        print("error: cannot read %s: %s" % (args.file, error), file=err)
        return 2
    if not urls:
        print("error: no URLs given — pass URLs, --file, or --stdin",
              file=err)
        return 2

    results = [check_url(url, max_redirects=args.max_redirects,
                         timeout=args.timeout) for url in urls]
    ok = sum(1 for r in results if r["outcome"] in ("OK", "CHAIN"))
    problems = len(results) - ok
    if args.json:
        # In JSON mode the summary goes to standard error, so the
        # standard output is clean JSON a script can parse.
        print(json.dumps(results, indent=2), file=out)
        print("%d checked, %d ok, %d problem(s)"
              % (len(results), ok, problems), file=err)
    else:
        for result in results:
            print(format_result(result), file=out)
        print("%d checked, %d ok, %d problem(s)"
              % (len(results), ok, problems), file=out)
    return 0 if problems == 0 else 1


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
