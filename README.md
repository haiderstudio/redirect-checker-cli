# redirect-checker-cli

Check URL redirect chains, flag loops and long chains.

[![CI](https://github.com/haiderstudio/redirect-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/redirect-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`redirect_checker` takes a list of URLs, follows each redirect chain
one hop at a time, and reports the final destination, the chain
length, and any problem — a loop, a chain longer than your limit, or
a final page that is not a success.

- It follows 301, 302, 303, 307, and 308 redirects, and prints the
  status code at each hop, so you can see whether a redirect is
  permanent or temporary.
- It flags loops: a URL that appears twice in one chain is reported
  as `LOOP` with how many redirects came first.
- It flags long chains: `--max-redirects N` (default 10) fails any
  chain with more than N redirects, reported as `LONG`.
- It reads URLs from the command line, from `--file` (one per line),
  or from `--stdin`, so it works in a pipe and in CI.
- It exits 0 when every URL ends in a success, and 1 when any URL
  loops, runs too long, ends in an error status, or cannot be
  fetched — so a CI step can fail the build on a bad redirect.
- `--json` prints the same results as JSON, for scripts that need to
  read them. In that mode the summary line goes to standard error,
  so the standard output is clean JSON.
- It is report-only and runs fully offline for local URLs: it sends
  requests only to the URLs you name, changes nothing on any site,
  and needs no API key.

## What it does NOT do

- It does not check every link on a site. It checks only the URLs
  you give it, one chain at a time. A full-site crawl is a different
  tool's job (see the Day 7 repo, broken-link-checker-cli, for
  checking links inside documents).
- It does not follow JavaScript or meta-refresh redirects. It
  follows HTTP 3xx responses only — a page that redirects with a
  `<meta>` tag or a script is reported by its HTTP status, not by
  where the browser would end up.
- It does not check page content, TLS certificates, or load time.
  It checks the chain and the final status, nothing more.
- It does not fix redirects. A loop or a long chain is reported
  with the exact hops, not repaired.

## Who it is for

Anyone who moves pages around and wants to know the redirects still
work: a developer checking a redirect map after a site move, someone
auditing short links before sharing them, or anyone adding a CI step
that fails the build when a listed URL loops or ends in a 404. If the
chain is clean, you get the final destination; if it is not, the
report says exactly which hop went wrong.

## How this differs from similar tools

Redirect checkers already exist, and most of them are web pages or
paid APIs: checkredirects.io and Geekflare trace chains behind an
API, and the w3c/link-checker checks every link on a whole site.
On GitHub, the exact name `"redirect-checker-cli"` returns 1 result:
statenweb/url-redirect-checker-cli (JavaScript, 0 stars). The wider
search (`redirect checker cli`, 23 results) is topped by
BaseMax/url-status-checker (Python, 3 stars), which checks status
codes, redirections, and load time for a list of URLs, and
marupibneyalid/site-health-checker (Python, 2 stars), which checks
availability, redirects, latency, and expected content. The closest
chain-only rivals are RahibAly/redirect-chain-checker-cli
(JavaScript, 0 stars), CrawlCove/redirect-chain-checker
(TypeScript, 0 stars, which also checks meta refreshes and HTTPS
downgrades), ksanyok/redirect-checker (JavaScript, 0 stars), and
phiilu/redirect-checker (JavaScript, 1 star, which builds nginx
maps). The npm package follow-redirect-url follows one URL at a
time and needs Node.

This tool does a narrower job: a Python standard-library-only CLI
that checks a list of URLs, reports the final destination and chain
length per URL, flags loops and long chains, and exits 1 on any
problem for CI — no install beyond Python, no browser, no API, no
full-site crawl.

## Install

Python standard library only — no packages to download. Clone the
repo and run it in place:

```sh
git clone https://github.com/haiderstudio/redirect-checker-cli.git
cd redirect-checker-cli
```

Python 3.10 or newer.

## Usage

The bundled examples run against a small demo server on your own
machine, so you can try the tool with real HTTP and no internet.
Start the server in one terminal:

```sh
python3 examples/demo_server.py 8123
```

Then check the example URLs:

```sh
python3 src/redirect_checker.py --file examples/urls.txt
```

Real output:

```text
OK      http://127.0.0.1:8123/ok -> http://127.0.0.1:8123/ok [200] (0 redirects)
CHAIN   http://127.0.0.1:8123/old -> http://127.0.0.1:8123/new [200] (1 redirect(s): 301)
CHAIN   http://127.0.0.1:8123/a -> http://127.0.0.1:8123/c [200] (2 redirect(s): 301, 302)
LOOP    http://127.0.0.1:8123/loop1 -> http://127.0.0.1:8123/loop1 (loop after 2 redirect(s))
LONG    http://127.0.0.1:8123/long1 -> http://127.0.0.1:8123/long12 (more than 10 redirect(s))
FAIL    http://127.0.0.1:8123/gone -> http://127.0.0.1:8123/gone (final status 404)
6 checked, 3 ok, 3 problem(s)
```

The command exits 1, because three of the six URLs have problems.
The same output is saved in `examples/sample-output.txt`.

Check one URL from the command line:

```sh
python3 src/redirect_checker.py http://127.0.0.1:8123/old
```

Real output:

```text
CHAIN   http://127.0.0.1:8123/old -> http://127.0.0.1:8123/new [200] (1 redirect(s): 301)
1 checked, 1 ok, 0 problem(s)
```

The command exits 0. A chain that lands on a success page is fine,
however many hops it took — up to the limit.

Check URLs from a pipe:

```sh
printf 'http://127.0.0.1:8123/ok\nhttp://127.0.0.1:8123/loop1\n' | python3 src/redirect_checker.py --stdin
```

Real output:

```text
OK      http://127.0.0.1:8123/ok -> http://127.0.0.1:8123/ok [200] (0 redirects)
LOOP    http://127.0.0.1:8123/loop1 -> http://127.0.0.1:8123/loop1 (loop after 2 redirect(s))
2 checked, 1 ok, 1 problem(s)
```

The command exits 1, because of the loop.

The same check as JSON:

```sh
python3 src/redirect_checker.py --json http://127.0.0.1:8123/old
```

Real output:

```text
[
  {
    "url": "http://127.0.0.1:8123/old",
    "hops": [
      {
        "url": "http://127.0.0.1:8123/old",
        "status": 301
      },
      {
        "url": "http://127.0.0.1:8123/new",
        "status": 200
      }
    ],
    "final_url": "http://127.0.0.1:8123/new",
    "final_status": 200,
    "outcome": "CHAIN",
    "detail": "1 redirect(s)"
  }
]
```

In `--json` mode the summary line (`1 checked, 1 ok, 0 problem(s)`)
goes to standard error, so the standard output is clean JSON a
script can parse.

## Examples

### 1. Fail CI on a looping redirect

```sh
python3 src/redirect_checker.py http://127.0.0.1:8123/loop1
echo $?
```

```text
LOOP    http://127.0.0.1:8123/loop1 -> http://127.0.0.1:8123/loop1 (loop after 2 redirect(s))
1 checked, 0 ok, 1 problem(s)
1
```

The exit code is 1 when a URL loops. Put the same command in CI
and the build fails until the redirect is fixed. With a clean URL
the same command prints `OK` and exits 0.

### 2. A chain that is too long

The demo server's `/long1` chain has 11 redirects. The default
limit is 10:

```sh
python3 src/redirect_checker.py http://127.0.0.1:8123/long1
```

```text
LONG    http://127.0.0.1:8123/long1 -> http://127.0.0.1:8123/long12 (more than 10 redirect(s))
1 checked, 0 ok, 1 problem(s)
```

Raise the limit and the same chain passes:

```sh
python3 src/redirect_checker.py --max-redirects 20 http://127.0.0.1:8123/long1
```

```text
CHAIN   http://127.0.0.1:8123/long1 -> http://127.0.0.1:8123/long12 [200] (11 redirect(s): 302, 302, 302, 302, 302, 302, 302, 302, 302, 302, 302)
1 checked, 1 ok, 0 problem(s)
```

### 3. Check a whole redirect map

Put one URL per line in a file (`#` lines and blank lines are
skipped) and check them all at once:

```sh
python3 src/redirect_checker.py --file examples/urls.txt
```

The six example URLs give the output shown in Usage above: 3 ok,
3 problems, exit 1.

## How it is tested

```sh
python3 tests/test_redirect_checker.py
```

45 tests, standard library `unittest` only — no third-party
packages. They cover: real redirect chains against a local test
HTTP server (direct 200, one and two redirects, loops including a
self-redirect, long chains with the limit raised and lowered, 404
and 500 finals, relative Location headers, 307 and 308, a redirect
with no Location header), the same logic with a fake fetcher
(non-HTTP URLs, connection errors, loop and long-chain counting),
the output lines (OK, CHAIN, LOOP), reading URLs from a file and
from stdin, the CLI (exit 0/1/2, `--max-redirects`, `--timeout`,
`--json`, `--version`, usage errors), the bundled examples (the
committed `examples/sample-output.txt` is compared byte-for-byte
against a fresh run on the demo server, the example script is run,
and every line of the sample output is checked to appear in this
README), the fresh-folder install check, and a check that the code
and the tests import standard library only.

No test touches the live internet: every network test runs against
a local server started inside the test, so the suite passes offline.

The bundled example is a real run, not made-up output:

```sh
sh examples/run-example.sh
```

It starts the demo server, checks the six example URLs, shows the
same check as JSON, and checks one URL with a short chain limit.
The committed `examples/sample-output.txt` is the output of the
check run.

## Contributing

Small, focused improvements are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

Built from scratch for this repo. The HTTP fetching uses Python's
standard `urllib` module; no code was copied from any existing
redirect checker.
