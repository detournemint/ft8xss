// Regression tests for the browser-side logic.
//
// The functions are lifted out of the shipped index.html by name and evaluated
// here, so these test the code the station actually serves rather than a copy
// of it that can quietly drift.
//
//     node tests/test_ui.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const HTML = readFileSync(join(ROOT, "ft8xss/static/index.html"), "utf8");
const SRC = HTML.match(/<script>([\s\S]*?)<\/script>/)[1];

// Pull out just the pieces under test. If a name is renamed or deleted the
// extraction fails loudly, which is the point.
function lift(name, kind = "function") {
  const re = kind === "function"
    ? new RegExp(`function\\s+${name}\\s*\\([\\s\\S]*?\\n\\}`, "m")
    : new RegExp(`const\\s+${name}\\s*=[\\s\\S]*?;`, "m");
  const m = SRC.match(re);
  if (!m) throw new Error(`could not find ${kind} ${name} in index.html`);
  return m[0];
}

const ctx = {};
const pieces = [
  lift("QSO_IDLE", "const"),
  lift("BAND_PLAN", "const"),
  lift("newestFirst", "const"),
  lift("ageOf"),
  lift("qsoActive"),
  lift("bandOf"),
  lift("esc"),
];
const { ageOf, qsoActive, bandOf, esc, newestFirst, QSO_IDLE } =
  new Function(`${pieces.join("\n")}
    return {ageOf, qsoActive, bandOf, esc, newestFirst, QSO_IDLE};`)();

// ---------------------------------------------------------------- harness --
let pass = 0, fail = 0;
const eq = (a, b, what) => {
  const ok = JSON.stringify(a) === JSON.stringify(b);
  if (ok) { pass++; } else { fail++; console.log(`  FAIL ${what}\n       got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`); }
};
const group = n => console.log(`\n${n}`);
const DAY = 86400000, MID = 12 * 3600000;   // noon UTC, in ms since midnight
const at = (msSinceMidnight, extra = {}) => ({ tms: msSinceMidnight, ...extra });

// ------------------------------------------------------------ decode ages --
group("decode age");
eq(ageOf(at(MID), MID + 30000) < 60, true, "30s ago reads as recent");
eq(ageOf(at(MID), MID + 2 * 3600000) > 3600, true, "two hours ago reads as old");
eq(ageOf(at(DAY - 15000), 15000) < 60, true,
   "30s across UTC midnight is recent, not a day old");
eq(ageOf(at(MID), 60000) > 3600, true, "yesterday noon is not recent at 00:01");
eq(ageOf(null, MID) > 1e6, true, "a missing decode is infinitely old");
eq(ageOf({}, MID) > 1e6, true, "a decode with no timestamp is infinitely old");

// ------------------------------------------------------------- QSO status --
group("current QSO");
const rx = t => at(t, { tx: false, to_me: true });
const tx = t => at(t, { tx: true });
eq(qsoActive("", [], 0, MID), false, "no DX call means no QSO");
eq(qsoActive("KG7MAV", [rx(MID - 5000)], 0, MID), true,
   "they replied five seconds ago");
eq(qsoActive("KG7MAV", [rx(MID - 600000)], 0, MID), false,
   "ten minutes of silence: the QSO is over");
eq(qsoActive("KG7MAV", [], 0, MID), false,
   "DX Call left populated by WSJT-X after a QSO is not a QSO");
eq(qsoActive("KG7MAV", [], MID - 5000, MID), true,
   "just clicked them, waiting for a first reply");
eq(qsoActive("KG7MAV", [], MID - 600000, MID), false,
   "selected ten minutes ago and never answered");
eq(qsoActive("KG7MAV", [tx(MID - 20000)], 0, MID), true,
   "we transmitted to them recently");
eq(QSO_IDLE >= 120, true, "an FT8 exchange has long gaps; do not expire early");

// ------------------------------------------------------------------ bands --
group("bands");
eq(bandOf(14074000), "20m", "20m FT8");
eq(bandOf(7074000), "40m", "40m FT8");
eq(bandOf(0), "", "no dial");
eq(bandOf(5000000), "", "WWV is not an amateur band");
eq(bandOf(14000000), "20m", "lower band edge");

// --------------------------------------------------------------- ordering --
group("band activity ordering");
const rows = [{ id: 1, tms: 100 }, { id: 3, tms: 300 }, { id: 2, tms: 200 }];
eq(rows.slice().sort(newestFirst).map(r => r.id), [3, 2, 1], "newest first");
const wrapped = [{ id: 9, tms: DAY - 15000 }, { id: 10, tms: 15000 }];
eq(wrapped.slice().sort(newestFirst)[0].id, 10,
   "ordering survives UTC midnight (id, not time-of-day)");
const tied = [{ id: 1, snr: -7 }, { id: 3, snr: -7 }, { id: 2, snr: -7 }];
const bySnr = (a, b) => (b.snr - a.snr) || newestFirst(a, b);
eq(tied.slice().sort(bySnr).map(r => r.id), [3, 2, 1],
   "equal SNR falls back to newest, not to insertion order");

// -------------------------------------------------------------- escaping --
group("escaping");
eq(esc("<img src=x onerror=1>"), "&lt;img src=x onerror=1&gt;",
   "markup in hamlib or systemd output is escaped");
eq(esc(null), "", "null is not the string 'null'");
eq(esc("K6XSS & CM88"), "K6XSS &amp; CM88", "ampersands");

// ------------------------------------------------------------------ done --
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
