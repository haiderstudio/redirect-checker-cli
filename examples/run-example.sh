#!/bin/sh
# Run the checker on the bundled examples against a local demo server.
# Run from the repo root: sh examples/run-example.sh
# The check exits 1 because three example URLs are bad on purpose —
# that is the expected result here.
set -e
cd "$(dirname "$0")/.."
python3 examples/demo_server.py 8123 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT INT TERM
# Wait until the demo server answers.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8123/ok', timeout=1)" 2>/dev/null; then
    break
  fi
  sleep 0.5
done
echo "--- check the example URLs ---"
python3 src/redirect_checker.py --file examples/urls.txt || true
echo "--- the same check, as JSON ---"
python3 src/redirect_checker.py --file examples/urls.txt --json | python3 -c "import json, sys; [print(r['url'], '->', r['outcome']) for r in json.load(sys.stdin)]"
echo "--- one URL, short chain limit ---"
python3 src/redirect_checker.py --max-redirects 1 http://127.0.0.1:8123/a || true
