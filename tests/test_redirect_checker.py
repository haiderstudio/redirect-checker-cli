#!/usr/bin/env python3
"""Tests for redirect_checker. Standard library unittest only.

Network tests run against a local test HTTP server (stdlib
http.server) started on an ephemeral port — nothing here touches
the live internet, so the suite passes offline on CI.
"""

import io
import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redirect_checker import (  # noqa: E402
    check_url,
    collect_urls,
    format_result,
    read_urls_from_file,
    run,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXAMPLES = ROOT / "examples"
SRC = ROOT / "src" / "redirect_checker.py"

# Routes for the local test server: path -> (status, Location, body).
TEST_ROUTES = {
    "/ok": (200, None, b"ok\n"),
    "/new": (200, None, b"new page\n"),
    "/c": (200, None, b"final page\n"),
    "/old": (301, "/new", b""),
    "/a": (301, "/b", b""),
    "/b": (302, "/c", b""),
    "/loop1": (302, "/loop2", b""),
    "/loop2": (302, "/loop1", b""),
    "/gone": (404, None, b"not here\n"),
    "/error": (500, None, b"broken\n"),
    "/self": (302, "/self", b""),
    "/rel": (302, "/ok", b""),
    "/noloc": (301, None, b""),
    "/perm": (308, "/ok", b""),
    "/temp": (307, "/ok", b""),
}
for _number in range(1, 12):
    TEST_ROUTES["/long%d" % _number] = (302, "/long%d" % (_number + 1), b"")
TEST_ROUTES["/long12"] = (200, None, b"end of a long chain\n")


class _TestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, location, body = TEST_ROUTES.get(
            self.path, (404, None, b"not here\n"))
        self.send_response(status)
        if location is not None:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class ServerTestCase(unittest.TestCase):
    """Base class that starts one local test server for the class."""

    server = None
    base = None

    @classmethod
    def setUpClass(cls):
        cls.server = _start_server()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()


def run_cli(argv, stdin_text=None):
    """Run the CLI in-process and capture stdout/stderr.

    Returns (code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    code = run(argv, stdin_text=stdin_text, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


class TestCheckUrlWithServer(ServerTestCase):
    def test_direct_200_is_ok(self):
        result = check_url(self.base + "/ok")
        self.assertEqual(result["outcome"], "OK")
        self.assertEqual(result["final_status"], 200)
        self.assertEqual(result["final_url"], self.base + "/ok")
        self.assertEqual(len(result["hops"]), 1)

    def test_one_redirect_is_chain(self):
        result = check_url(self.base + "/old")
        self.assertEqual(result["outcome"], "CHAIN")
        self.assertEqual(result["final_url"], self.base + "/new")
        self.assertEqual(result["final_status"], 200)
        self.assertEqual(
            [h["status"] for h in result["hops"]], [301, 200])

    def test_two_redirect_chain(self):
        result = check_url(self.base + "/a")
        self.assertEqual(result["outcome"], "CHAIN")
        self.assertEqual(result["final_url"], self.base + "/c")
        self.assertEqual(
            [h["status"] for h in result["hops"]], [301, 302, 200])

    def test_loop_is_flagged(self):
        result = check_url(self.base + "/loop1")
        self.assertEqual(result["outcome"], "LOOP")
        self.assertEqual(result["detail"], "loop after 2 redirect(s)")

    def test_self_redirect_is_loop(self):
        result = check_url(self.base + "/self")
        self.assertEqual(result["outcome"], "LOOP")
        self.assertEqual(result["detail"], "loop after 1 redirect(s)")

    def test_long_chain_is_flagged(self):
        result = check_url(self.base + "/long1")
        self.assertEqual(result["outcome"], "LONG")
        self.assertEqual(result["detail"], "more than 10 redirect(s)")

    def test_long_chain_passes_with_higher_limit(self):
        result = check_url(self.base + "/long1", max_redirects=20)
        self.assertEqual(result["outcome"], "CHAIN")
        self.assertEqual(result["final_url"], self.base + "/long12")

    def test_404_is_fail(self):
        result = check_url(self.base + "/gone")
        self.assertEqual(result["outcome"], "FAIL")
        self.assertEqual(result["final_status"], 404)
        self.assertEqual(result["detail"], "final status 404")

    def test_500_is_fail(self):
        result = check_url(self.base + "/error")
        self.assertEqual(result["outcome"], "FAIL")
        self.assertEqual(result["final_status"], 500)

    def test_relative_location_is_resolved(self):
        result = check_url(self.base + "/rel")
        self.assertEqual(result["outcome"], "CHAIN")
        self.assertEqual(result["final_url"], self.base + "/ok")

    def test_307_and_308_are_followed(self):
        for path in ("/temp", "/perm"):
            with self.subTest(path=path):
                result = check_url(self.base + path)
                self.assertEqual(result["outcome"], "CHAIN")
                self.assertEqual(result["final_url"], self.base + "/ok")

    def test_redirect_with_no_location_is_fail(self):
        result = check_url(self.base + "/noloc")
        self.assertEqual(result["outcome"], "FAIL")
        self.assertEqual(result["detail"],
                         "redirect with no Location header")


class TestCheckUrlWithFakeFetcher(unittest.TestCase):
    def test_non_http_url_is_error(self):
        result = check_url("ftp://example.com/file")
        self.assertEqual(result["outcome"], "ERROR")
        self.assertEqual(result["detail"], "not an http(s) URL")

    def test_bare_hostname_is_error(self):
        result = check_url("example.com/page")
        self.assertEqual(result["outcome"], "ERROR")

    def test_connection_error_is_error(self):
        def failing(url, timeout):
            raise urllib.error.URLError("refused")

        result = check_url("http://127.0.0.1:9/x", fetcher=failing)
        self.assertEqual(result["outcome"], "ERROR")
        self.assertIn("refused", result["detail"])

    def test_loop_via_fake_fetcher(self):
        mapping = {
            "http://x/a": (302, "http://x/b"),
            "http://x/b": (302, "http://x/a"),
        }

        def fetch(url, timeout):
            return mapping[url]

        result = check_url("http://x/a", fetcher=fetch)
        self.assertEqual(result["outcome"], "LOOP")
        self.assertEqual(result["detail"], "loop after 2 redirect(s)")

    def test_long_via_fake_fetcher(self):
        def fetch(url, timeout):
            number = int(url.rsplit("/", 1)[-1])
            return 302, "http://x/%d" % (number + 1)

        result = check_url("http://x/1", max_redirects=3, fetcher=fetch)
        self.assertEqual(result["outcome"], "LONG")
        self.assertEqual(result["detail"], "more than 3 redirect(s)")

    def test_zero_max_redirects(self):
        def fetch(url, timeout):
            return 302, "http://x/b"

        result = check_url("http://x/a", max_redirects=0, fetcher=fetch)
        self.assertEqual(result["outcome"], "LONG")


class TestFormatResult(unittest.TestCase):
    def test_ok_line(self):
        result = check_url("http://x/ok", fetcher=lambda u, t: (200, None))
        line = format_result(result)
        self.assertEqual(line, "OK      http://x/ok -> http://x/ok "
                               "[200] (0 redirects)")

    def test_chain_line_lists_codes(self):
        mapping = {"http://x/a": (301, "http://x/b"),
                   "http://x/b": (200, None)}

        def fetch(url, timeout):
            return mapping[url]

        line = format_result(check_url("http://x/a", fetcher=fetch))
        self.assertEqual(line, "CHAIN   http://x/a -> http://x/b "
                               "[200] (1 redirect(s): 301)")

    def test_loop_line(self):
        mapping = {"http://x/a": (302, "http://x/b"),
                   "http://x/b": (302, "http://x/a")}

        def fetch(url, timeout):
            return mapping[url]

        line = format_result(check_url("http://x/a", fetcher=fetch))
        self.assertEqual(line, "LOOP    http://x/a -> http://x/a "
                               "(loop after 2 redirect(s))")


class TestReadUrls(unittest.TestCase):
    def test_file_skips_blanks_and_comments(self):
        path = HERE / "tmp-urls.txt"
        path.write_text("http://a.example/\n\n# a note\n  http://b.example/  \n")
        try:
            self.assertEqual(read_urls_from_file(path),
                             ["http://a.example/", "http://b.example/"])
        finally:
            path.unlink()

    def test_collect_from_stdin_text(self):
        class Args:
            urls = []
            file = None
            stdin = True

        urls = collect_urls(Args(), stdin_text="http://a.example/\n\n")
        self.assertEqual(urls, ["http://a.example/"])

    def test_collect_positional_and_file(self):
        path = HERE / "tmp-urls2.txt"
        path.write_text("http://b.example/\n")
        try:
            class Args:
                urls = ["http://a.example/"]
                file = str(path)
                stdin = False

            self.assertEqual(collect_urls(Args()),
                             ["http://a.example/", "http://b.example/"])
        finally:
            path.unlink()


class TestCliWithServer(ServerTestCase):
    def test_check_file_exits_1_with_problems(self):
        path = HERE / "tmp-urls3.txt"
        path.write_text("\n".join([
            self.base + "/ok",
            self.base + "/loop1",
            self.base + "/gone",
        ]) + "\n")
        try:
            code, out, _err = run_cli(["--file", str(path)])
        finally:
            path.unlink()
        self.assertEqual(code, 1)
        self.assertIn("3 checked, 1 ok, 2 problem(s)", out)

    def test_single_ok_url_exits_0(self):
        code, out, _err = run_cli([self.base + "/ok"])
        self.assertEqual(code, 0)
        self.assertIn("OK      " + self.base + "/ok", out)
        self.assertIn("1 checked, 1 ok, 0 problem(s)", out)

    def test_mixed_urls_exit_1(self):
        code, out, _err = run_cli(
            [self.base + "/ok", self.base + "/loop1", self.base + "/gone"])
        self.assertEqual(code, 1)
        self.assertIn("3 checked, 1 ok, 2 problem(s)", out)
        self.assertIn("LOOP", out)
        self.assertIn("FAIL", out)

    def test_stdin_input(self):
        code, out, _err = run_cli(
            ["--stdin"],
            stdin_text=self.base + "/ok\n" + self.base + "/old\n")
        self.assertEqual(code, 0)
        self.assertIn("2 checked, 2 ok, 0 problem(s)", out)

    def test_max_redirects_flag(self):
        code, out, _err = run_cli(
            ["--max-redirects", "1", self.base + "/a"])
        self.assertEqual(code, 1)
        self.assertIn("LONG", out)

    def test_json_output(self):
        code, out, err = run_cli(
            ["--json", self.base + "/ok", self.base + "/gone"])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual([r["outcome"] for r in data], ["OK", "FAIL"])
        self.assertEqual(data[0]["final_status"], 200)
        self.assertEqual(data[1]["final_status"], 404)
        # In JSON mode the summary goes to stderr, so stdout is
        # clean JSON a script can parse.
        self.assertIn("2 checked, 1 ok, 1 problem(s)", err)

    def test_no_urls_is_usage_error(self):
        code, _out, err = run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("no URLs given", err)

    def test_missing_file_is_usage_error(self):
        code, _out, err = run_cli(["--file", "no-such-file.txt"])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_negative_max_redirects_is_usage_error(self):
        code, _out, err = run_cli(
            ["--max-redirects", "-1", self.base + "/ok"])
        self.assertEqual(code, 2)
        self.assertIn("--max-redirects", err)

    def test_bad_timeout_is_usage_error(self):
        code, _out, err = run_cli(["--timeout", "0", self.base + "/ok"])
        self.assertEqual(code, 2)
        self.assertIn("--timeout", err)

    def test_bad_flag_is_usage_error(self):
        code, _out, err = run_cli(["--nope", self.base + "/ok"])
        self.assertEqual(code, 2)
        self.assertIn("unrecognized arguments", err)

    def test_version_flag(self):
        code, out, _err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("redirect-checker-cli", out)


class TestExamples(unittest.TestCase):
    def test_sample_output_matches_fresh_run(self):
        """Start the demo server on 8123, run the checker on the
        bundled URL list, compare byte-for-byte with the committed
        sample output."""
        server = subprocess.Popen(
            [sys.executable, str(EXAMPLES / "demo_server.py"), "8123"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(20):
                try:
                    import urllib.request
                    urllib.request.urlopen(
                        "http://127.0.0.1:8123/ok", timeout=1)
                    break
                except OSError:
                    import time
                    time.sleep(0.25)
            code, out, _err = run_cli(
                ["--file", str(EXAMPLES / "urls.txt")])
            self.assertEqual(code, 1)
            committed = (EXAMPLES / "sample-output.txt").read_text()
            self.assertEqual(out, committed)
        finally:
            server.terminate()
            server.wait(timeout=5)

    def test_run_example_script(self):
        result = subprocess.run(
            ["sh", str(EXAMPLES / "run-example.sh")],
            capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn("6 checked, 3 ok, 3 problem(s)", result.stdout)
        self.assertIn("LOOP", result.stdout)
        self.assertIn("http://127.0.0.1:8123/ok -> OK", result.stdout)

    def test_readme_quoted_outputs_match_sample(self):
        readme = (ROOT / "README.md").read_text()
        sample = (EXAMPLES / "sample-output.txt").read_text()
        for line in sample.strip().splitlines():
            self.assertIn(line, readme,
                          "sample-output line missing from README: %r" % line)

    def test_readme_install_commands_run(self):
        """Copy the build to a fresh folder and run the README's
        install/usage commands there. Runs one small non-recursive
        test from the fresh copy — running the whole suite again
        would recurse into this test forever."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "redirect-checker-cli"
            shutil.copytree(ROOT, fresh, ignore=shutil.ignore_patterns(
                "__pycache__", ".git"))
            result = subprocess.run(
                [sys.executable, "tests/test_redirect_checker.py",
                 "TestCheckUrlWithFakeFetcher"],
                capture_output=True, text=True, cwd=fresh, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            version = subprocess.run(
                [sys.executable, "src/redirect_checker.py", "--version"],
                capture_output=True, text=True, cwd=fresh, timeout=30)
            self.assertEqual(version.returncode, 0)
            self.assertIn("redirect-checker-cli", version.stdout)


class TestRepoHygiene(unittest.TestCase):
    def test_stdlib_only_imports(self):
        allowed = {
            "argparse", "contextlib", "http", "io", "json", "os", "re",
            "shutil", "socket", "subprocess", "sys", "tempfile",
            "threading", "time", "unittest", "urllib", "pathlib",
            "redirect_checker",
        }
        for path in list((ROOT / "src").rglob("*.py")) + \
                list((ROOT / "tests").rglob("*.py")):
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith("import "):
                    for name in line[7:].split(","):
                        top = name.strip().split(".")[0].split(" ")[0]
                        self.assertIn(top, allowed, "%s in %s" % (top, path))
                elif line.startswith("from "):
                    top = line.split()[1].split(".")[0]
                    self.assertIn(top, allowed, "%s in %s" % (top, path))

    def test_no_placeholders_or_secrets(self):
        banned = (
            "TODO", "FIXME", "lorem", "coming soon",
            "API_KEY", "api_key", "password =",
        )
        # The tests directory is excluded: the test file itself names
        # the banned words in its own check list. .git is excluded:
        # GitHub's checkout ships sample hooks under .git/hooks/ that
        # contain "TODO" (Day 21 CI lesson).
        shipped = [
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and "__pycache__" not in str(path)
            and ".git" not in path.parts
            and "tests" not in path.parts
        ]
        for path in shipped:
            text = path.read_text(errors="ignore")
            for word in banned:
                self.assertNotIn(word, text, "%s in %s" % (word, path))

    def test_no_absolute_paths(self):
        shipped = [
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and "__pycache__" not in str(path)
            and ".git" not in path.parts
            and "tests" not in path.parts
        ]
        for path in shipped:
            text = path.read_text(errors="ignore")
            self.assertNotIn("/home/hatch", text,
                             "absolute path in %s" % path)
            self.assertNotIn("/tmp/", text, "absolute path in %s" % path)

    def test_gitignore_lists_env_first(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_the_test_file(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("python3 tests/test_redirect_checker.py", ci)
        self.assertIn("3.12", ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
