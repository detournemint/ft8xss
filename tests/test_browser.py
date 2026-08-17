"""End-to-end tests for the interface, in a real browser.

Everything else in this suite tests functions. This one loads the page the
station actually serves, lets it render, and drives real events at it — the only
way to catch a handler that is wired to the wrong element, a row template that
lost an attribute, or a script that throws on load and leaves a blank page.

The demo build is used as the harness because it carries its own data and needs
no radio. Skipped, not failed, when no chromium is installed.

    python3 tests/test_browser.py
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = next((c for c in ("chromium", "chromium-browser", "google-chrome",
                           "google-chrome-stable")
               if shutil.which(c)), None)

# Runs inside the page: capture what it tries to send, then drive real events.
PROBE = r"""
<script>
(function(){
  const sent = [];
  const orig = WebSocket.prototype.send;
  WebSocket.prototype.send = function(raw){
    try { sent.push(JSON.parse(raw)); } catch(e){}
    return orig.call(this, raw);
  };
  const dbl = el => el.dispatchEvent(
      new MouseEvent("dblclick", {bubbles:true, cancelable:true}));
  const click = el => el.dispatchEvent(
      new MouseEvent("click", {bubbles:true, cancelable:true}));
  const calls = () => sent.filter(m => m.action === "call").length;

  setTimeout(() => {
    const r = {};
    r.page_rendered = !!document.querySelector("#rows tr");
    r.no_console_errors = !window.__err;

    const row = document.querySelector("#rows tr.hail[data-id]");
    r.row_is_hailable = !!row;
    if (row){
      const want = +row.dataset.id, before = calls();
      dbl(row.querySelector("td:nth-child(6)") || row);
      r.dblclick_calls_that_station =
        sent.some(m => m.action === "call" && m.id === want) &&
        calls() === before + 1;
    }

    const txrow = document.querySelector("#rows tr.txrow");
    r.tx_row_present = !!txrow;
    if (txrow){ const before = calls(); dbl(txrow);
                r.own_tx_row_not_callable = calls() === before; }

    const btn = document.querySelector("#rows button[data-id]");
    if (btn){ const before = calls(); click(btn);
              r.call_button_still_works = calls() === before + 1; }

    const link = document.querySelector("#rows a[href*='qrz.com']");
    if (link){ const before = sent.length; dbl(link);
               r.callsign_links_left_alone = sent.length === before; }

    r.stop_button_present = !!document.querySelector("#halt");
    document.title = "RESULT " + JSON.stringify(r);
  }, 2500);
})();
window.addEventListener("error", () => { window.__err = true; });
</script>
"""


@unittest.skipUnless(CHROME, "no chromium installed")
class Interface(unittest.TestCase):
    results = None

    @classmethod
    def setUpClass(cls):
        # rebuild so we are testing the page as it stands, not a stale artefact
        subprocess.run([sys.executable, "docs/build_demo.py"], cwd=ROOT,
                       check=True, capture_output=True)
        page = (ROOT / "docs/demo/index.html").read_text()
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
            fh.write(page.replace("</body>", PROBE + "</body>"))
            path = fh.name
        try:
            out = subprocess.run(
                [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
                 "--virtual-time-budget=7000", "--dump-dom", f"file://{path}"],
                cwd=ROOT, capture_output=True, text=True, timeout=120)
        finally:
            Path(path).unlink(missing_ok=True)
        m = re.search(r"RESULT (\{.*?\})", out.stdout or "")
        if not m:
            raise AssertionError("the page produced no result — it probably "
                                 "failed to render at all")
        cls.results = json.loads(m.group(1))

    def check(self, key):
        self.assertIn(key, self.results, f"{key} did not run")
        self.assertTrue(self.results[key], key)

    def test_page_renders(self):
        self.check("page_rendered")

    def test_no_script_errors_on_load(self):
        """A throw during load leaves an operator with a blank page."""
        self.check("no_console_errors")

    def test_rows_are_hailable(self):
        self.check("row_is_hailable")

    def test_double_click_calls_that_station(self):
        self.check("dblclick_calls_that_station")

    def test_own_transmission_is_not_callable(self):
        self.check("tx_row_present")
        self.check("own_tx_row_not_callable")

    def test_call_button_still_works(self):
        """The button is the discoverable path, and the only one on a
        touchscreen. Adding double-click must not cost it."""
        self.check("call_button_still_works")

    def test_callsign_links_are_left_alone(self):
        """Double-clicking a callsign should reach QRZ, not the transmitter."""
        self.check("callsign_links_left_alone")

    def test_stop_button_exists(self):
        self.check("stop_button_present")


if __name__ == "__main__":
    unittest.main(verbosity=2)
