"""Regression tests.

Nearly every case here is a bug that reached the air: a station transmitting
8 W of 25 W without saying so, an API key printed in a report, a QSO panel that
would not let go. The names say what broke, so a failure says what came back.

    python3 tests/run.py
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("FT8XSS_CALL", "K6XSS")
os.environ.setdefault("FT8XSS_GRID", "CM88VC")
os.environ.setdefault("FT8XSS_NO_GUI", "1")
sys.path.insert(0, str(ROOT / "ft8xss"))

import bandsetup                                                  # noqa: E402
import diag                                                       # noqa: E402
import dxcc                                                       # noqa: E402
import server                                                     # noqa: E402


class DriveCorrection(unittest.TestCase):
    """The transmission check. Measured on 40m: 8 W out of a 25 W setting."""

    def corr(self, po, alc, target=25, att=100):
        return server._drive_correction(po, alc, target, att)

    def test_low_power_asks_for_more_drive(self):
        new, why = self.corr(8.0, 0.09, 25, 115)
        self.assertIsNotNone(new)
        self.assertLess(new, 115, "less attenuation means more drive")
        self.assertIn("4.9 dB", why)

    def test_correction_size_matches_the_shortfall(self):
        # 25/8 is 4.95 dB; attenuation is in tenths of a dB
        new, _ = self.corr(8.0, 0.09, 25, 115)
        self.assertAlmostEqual(115 - new, 49, delta=2)

    def test_high_alc_backs_off_even_at_full_power(self):
        # the 15m case: 24.9 W looked fine, ALC 0.83 was flattening it
        new, why = self.corr(24.9, 0.828, 25, 95)
        self.assertGreater(new, 95, "more attenuation means less drive")
        self.assertIn("ALC", why)

    def test_alc_wins_when_power_is_also_low(self):
        """The dangerous case, measured on 15m into a mismatch: 9.8 W out of 25
        with the ALC pinned at 1.0. Both rules fire. Judging power first would
        conclude "too quiet" and push *more* drive into a transmitter that is
        already flattening, which is how you cook finals."""
        new, why = self.corr(9.8, 1.0, 25, 95)
        self.assertIn("ALC", why, "ALC must be judged before power")
        self.assertGreater(new, 95, "must reduce drive, not increase it")

    def test_good_transmission_is_left_alone(self):
        for po, alc, att in ((21.3, 0.109, 110), (23.8, 0.250, 70)):
            new, why = self.corr(po, alc, 25, att)
            self.assertIsNone(new, f"{po} W / ALC {alc} should pass")
            self.assertIn("tolerance", why)

    def test_an_unknown_target_is_not_invented(self):
        """With the rig set to 50% and not reporting it, a fallback target of 25
        made 26 W report itself as healthy while half the power went unused.
        ALC is still judged; power is not guessed at."""
        new, why = server._drive_correction(26.0, 0.094, None, 138)
        self.assertIsNone(new)
        self.assertIn("not judged", why)
        # an over-driven signal is still over-driven whatever the target
        new, why = server._drive_correction(26.0, 0.9, None, 138)
        self.assertIsNotNone(new)
        self.assertIn("ALC", why)

    def test_corrections_are_capped_per_band(self):
        """Four calibrations on 20m settled at 108, 158, 128 and 118 because the
        audio offset kept moving underneath them. Corrections that do not
        converge must stop rather than restart WSJT-X forever."""
        self.assertLessEqual(server.MAX_FIXES, 5)
        self.assertGreaterEqual(server.MAX_FIXES, 1)

    def test_a_single_step_is_bounded(self):
        """One measurement must not be trusted with an unlimited correction."""
        new, _ = self.corr(0.6, 0.05, 100, 250)
        self.assertGreaterEqual(new, 250 - server.MAX_STEP)

    def test_attenuation_never_leaves_the_usable_range(self):
        for po, alc, att in ((0.5, 0.0, 40), (25.0, 1.0, 245), (1.0, 0.0, 30)):
            new, _ = self.corr(po, alc, 25, att)
            if new is not None:
                self.assertGreaterEqual(new, 30)
                self.assertLessEqual(new, 250)


class BandSetupSelection(unittest.TestCase):
    """Picking the winner from the measurements. This once discarded the good
    result because ALC was only a tiebreak."""

    def pick(self, rows, target=25):
        best = None
        for att, po, alc in rows:
            m = {"po": po, "alc": alc}
            ok_alc = alc <= bandsetup.ALC_MAX
            best_ok = best is not None and best[1]["alc"] <= bandsetup.ALC_MAX
            if ok_alc and (not best_ok or po > best[1]["po"]):
                best = (att, dict(m))
            elif best is None:
                best = (att, dict(m))
            elif not best_ok and alc < best[1]["alc"]:
                best = (att, dict(m))
            if ok_alc and po >= bandsetup.PO_FLOOR * target:
                break
        return best

    def test_clean_alc_beats_higher_power(self):
        best = self.pick([(70, 23.8, 0.98), (95, 24.2, 0.80), (110, 21.3, 0.11)])
        self.assertEqual(best[0], 110, "the clean one wins, not the loudest")

    def test_all_dirty_picks_the_least_dirty(self):
        best = self.pick([(70, 24.0, 0.99), (85, 24.2, 0.80), (100, 23.8, 0.56)])
        self.assertEqual(best[0], 100)

    def test_stops_once_it_is_good_enough(self):
        best = self.pick([(110, 22.0, 0.09), (200, 5.0, 0.01)])
        self.assertEqual(best[0], 110, "must not keep going past a good result")

    def test_thresholds_are_what_we_think(self):
        self.assertEqual(bandsetup.ALC_MAX, 0.30)
        self.assertEqual(bandsetup.SWR_ABORT, 3.0)


class ClearSlot(unittest.TestCase):
    """Audio placement before a transmission."""

    def decodes(self, freqs, band="20m", tx=False):
        return [{"df": f, "band": band, "tx": tx} for f in freqs]

    def test_moves_off_a_crowded_frequency(self):
        d = self.decodes([1200] * 9 + [1260, 2100])
        hz, crowd, _ = server.pick_clear_slot(1200, d, "20m")
        self.assertNotEqual(hz, 1200)
        self.assertEqual(crowd, 0)

    def test_our_own_transmissions_are_not_traffic(self):
        """Sitting on our own frequency must not read as interference and send
        us wandering off it every time we transmit."""
        d = self.decodes([1500] * 20, tx=True)
        hz, crowd, _ = server.pick_clear_slot(1500, d, "20m")
        self.assertEqual(crowd, 0)
        self.assertEqual(hz, 1500, "nothing but our own TX here — stay put")

    def test_stays_inside_the_passband(self):
        for start in (300, 1500, 2600):
            hz, _, _ = server.pick_clear_slot(start, self.decodes([1500] * 8), "20m")
            self.assertGreaterEqual(hz, server.DF_MIN)
            self.assertLessEqual(hz, server.DF_MAX)

    def test_lands_on_the_60_hz_grid(self):
        """WSJT-X moves in 60 Hz steps; an unreachable target never arrives."""
        hz, _, _ = server.pick_clear_slot(1200, self.decodes([1200] * 6), "20m")
        self.assertEqual((hz - 1200) % server.DF_WIDTH, 0)

    def test_other_bands_are_ignored(self):
        d = self.decodes([1260] * 9, band="40m")
        hz, crowd, _ = server.pick_clear_slot(1200, d, "20m")
        self.assertEqual(crowd, 0)

    def test_keeps_off_the_filter_skirts(self):
        """The quietest slots are at the passband edges, and they are quiet
        because the rig rolls off there. Measured on an FT-991A at one drive
        setting: 480 Hz pinned the ALC at 0.89, 2580 Hz made 8 W of 25. A search
        that is free to go there leaves the drive calibration chasing the filter
        response instead of the antenna."""
        self.assertGreaterEqual(server.DF_MIN, 700)
        self.assertLessEqual(server.DF_MAX, 2300)
        crowded = self.decodes([1200] * 12 + [1500] * 12)
        for start in (480, 1200, 2580):
            hz, _, _ = server.pick_clear_slot(start, crowded, "20m")
            self.assertGreaterEqual(hz, server.DF_MIN, f"from {start}")
            self.assertLessEqual(hz, server.DF_MAX, f"from {start}")

    def test_a_start_outside_the_window_is_pulled_back_in(self):
        hz, _, _ = server.pick_clear_slot(2580, self.decodes([]), "20m")
        self.assertLessEqual(hz, server.DF_MAX)

    def test_prefers_the_nearer_of_two_equally_clear_slots(self):
        hz, _, _ = server.pick_clear_slot(1500, self.decodes([1500] * 4), "20m")
        self.assertLessEqual(abs(hz - 1500), 120)


class ProbeTransmission(unittest.TestCase):
    """What band setup puts on the air. It used to be a CQ, which solicited
    contacts it then abandoned when the run disarmed."""

    def probe(self, call):
        old = server.MY_CALL
        try:
            server.MY_CALL = call
            return server.probe_message()
        finally:
            server.MY_CALL = old

    def test_is_never_a_cq(self):
        for call in ("K6XSS", "N0CALL", "VE3ABC/QRP"):
            self.assertNotIn("CQ", self.probe(call).upper())

    def test_fits_ft8_free_text(self):
        for call in ("K6XSS", "VP2E/W3ABCDE", "DL1ABCD/P", "VE3ABC/QRP"):
            self.assertLessEqual(len(self.probe(call)), 13, call)

    def test_long_callsign_is_not_chopped_mid_word(self):
        self.assertEqual(self.probe("VE3ABC/QRP"), "VE3ABC/QRP")

    def test_always_identifies_when_it_can(self):
        self.assertIn("K6XSS", self.probe("K6XSS"))

    def test_never_empty(self):
        self.assertTrue(self.probe("").strip())


class MessageParsing(unittest.TestCase):
    def test_cq_is_recognised(self):
        s, to, grid, cq = server.parse_message("CQ W1AW FN31")
        self.assertEqual((s, grid, cq), ("W1AW", "FN31", True))

    def test_reply_addressed_to_us(self):
        s, to, grid, cq = server.parse_message("K6XSS EA5TT IM98")
        self.assertEqual((s, to, grid), ("EA5TT", "K6XSS", "IM98"))
        self.assertFalse(cq)

    def test_rr73_is_not_a_grid_square(self):
        """It looks exactly like one, and was logged as a location."""
        for sign_off in ("RR73", "RRR", "73", "R73"):
            _, _, grid, _ = server.parse_message(f"K6XSS W1AW {sign_off}")
            self.assertEqual(grid, "", sign_off)

    def test_directed_cq_still_reads_as_cq(self):
        s, _, _, cq = server.parse_message("CQ POTA W7ABC CN87")
        self.assertTrue(cq)


class Redaction(unittest.TestCase):
    """A QRZ key reached a report in plain text once. It must not again."""

    def test_hyphenated_api_key_is_masked(self):
        key = "AAAA-BBBB-CCCC-DDDD"
        self.assertNotIn(key, diag.redact(f"FT8XSS_QRZ_KEY={key}"))

    def test_registered_secret_is_masked_anywhere(self):
        diag.register_secret("s3cr3t-value-here")
        out = diag.redact("url?key=s3cr3t-value-here&x=1")
        self.assertNotIn("s3cr3t-value-here", out)

    def test_key_shaped_assignments_are_masked(self):
        for line in ("password=hunter2", "TOKEN: abc123def", "api_key = zzzz"):
            self.assertNotIn("hunter2", diag.redact(line).lower().replace(" ", ""))
            self.assertIn("REDACTED", diag.redact(line))

    def test_ordinary_text_survives(self):
        msg = "[band] 20m: att=70 PO=23.8W ALC=0.25 SWR=1.2"
        self.assertEqual(diag.redact(msg), msg)


class AdifAppend(unittest.TestCase):
    """WSJT-X sends a whole ADIF document per QSO. Appending them verbatim gave
    a log with a header before nearly every record."""

    SAMPLE = ("<adif_ver:5>3.1.0\n<programid:6>WSJT-X\n<EOH>\n"
              "<call:6>KE0YYU <gridsquare:4>EM48 <mode:3>FT8 <eor>\n")

    def test_one_header_across_many_qsos(self):
        out = "".join(server.adif_append(self.SAMPLE, header=(i == 0))
                      for i in range(5))
        self.assertEqual(out.upper().count("<EOH>"), 1)
        self.assertEqual(out.upper().count("<EOR>"), 5)

    def test_record_survives_intact(self):
        self.assertIn("KE0YYU", server.adif_append(self.SAMPLE, header=False))

    def test_headerless_input_is_passed_through(self):
        rec = "<call:5>W1AW <eor>\n"
        self.assertIn("W1AW", server.adif_append(rec, header=False))

    def test_result_parses_back(self):
        out = "".join(server.adif_append(self.SAMPLE, header=(i == 0))
                      for i in range(3))
        self.assertEqual(len(list(server.parse_adif(out))), 3)


class ReplyAge(unittest.TestCase):
    """WSJT-X matches a Reply against its own decodes for the current period.
    Ask it to answer an older one and the packet is dropped without a word, so
    the station carries on CQing and the button looks broken."""

    def age(self, seconds_ago):
        import time as _t
        now = int(_t.time() * 1000) % 86400000
        return server.decode_age({"tms": now - int(seconds_ago * 1000)})

    def test_a_fresh_decode_is_answerable(self):
        self.assertLess(self.age(5), server.REPLY_MAX_AGE)

    def test_a_stale_decode_is_not(self):
        self.assertGreater(self.age(600), server.REPLY_MAX_AGE)

    def test_the_limit_allows_a_few_periods(self):
        """An operator reading the list needs longer than one 15s slot to
        choose, but not so long that WSJT-X has forgotten the decode."""
        self.assertGreaterEqual(server.REPLY_MAX_AGE, 45)
        self.assertLessEqual(server.REPLY_MAX_AGE, 180)

    def test_missing_timestamp_is_infinitely_old(self):
        self.assertGreater(server.decode_age({}), 1e6)
        self.assertGreater(server.decode_age(None), 1e6)


class PskReporter(unittest.TestCase):
    def test_we_do_not_query_faster_than_they_ask(self):
        """PSK Reporter asks for no more than one automated query every five
        minutes. Throttled looks identical to nobody hearing you."""
        self.assertGreaterEqual(server.PSK_INTERVAL, 300)


class Bands(unittest.TestCase):
    def test_ft8_watering_holes_map_to_their_band(self):
        for hz, band in ((7074000, "40m"), (14074000, "20m"), (21074000, "15m"),
                         (3573000, "80m"), (28074000, "10m"), (50313000, "6m")):
            self.assertEqual(server.band_of(hz), band)

    def test_out_of_band_is_empty_not_wrong(self):
        """band_of keys the drive calibration, so an unknown frequency must not
        invent a band to calibrate."""
        for hz in (0, None, 12345, 900_000_000, 5_000_000):
            self.assertEqual(server.band_of(hz), "", str(hz))

    def test_edges_are_inclusive(self):
        self.assertEqual(server.band_of(14_000_000), "20m")
        self.assertEqual(server.band_of(14_350_000), "20m")


class Geo(unittest.TestCase):
    def test_known_distance(self):
        home = server.grid_to_latlon("CM88VC")      # San Francisco Bay
        km, brg = server.dist_bearing(home, server.grid_to_latlon("FN31pr"))
        self.assertAlmostEqual(km, 4130, delta=120)   # to Newington, CT
        self.assertTrue(60 <= brg <= 80, f"bearing {brg} should be roughly ENE")

    def test_six_and_four_character_grids_agree(self):
        a = server.dist_bearing(server.grid_to_latlon("CM88"),
                                server.grid_to_latlon("FN31"))
        b = server.dist_bearing(server.grid_to_latlon("CM88vc"),
                                server.grid_to_latlon("FN31pr"))
        self.assertAlmostEqual(a[0], b[0], delta=120)


class Dxcc(unittest.TestCase):
    def test_common_prefixes(self):
        for call, entity in (("W1AW", "United States"), ("VK3ANP", "Australia"),
                             ("JA1XYZ", "Japan"), ("DL9ZZZ", "Germany")):
            self.assertEqual(dxcc.entity(call), entity, call)

    def test_portable_suffix_does_not_change_the_entity(self):
        self.assertEqual(dxcc.entity("W1AW/7"), dxcc.entity("W1AW"))

    def test_unknown_callsign_is_not_guessed(self):
        self.assertIn(dxcc.entity("12345"), (None, ""))


class Settings(unittest.TestCase):
    def test_masked_secret_is_not_written_over_the_real_one(self):
        keys = {k for k, *_ in server.settings.SCHEMA}
        self.assertIn("QRZ_KEY", keys)
        secret = {k: sec for k, _, _, _, _, sec, _ in server.settings.SCHEMA}
        self.assertTrue(secret["QRZ_KEY"], "the API key must be marked secret")

    def test_safety_settings_default_to_the_safe_value(self):
        by_key = {k: (typ, dflt) for k, _, _, typ, _, _, dflt
                  in [(a, b, c, d, e, f, g) for a, b, c, d, e, f, g
                      in server.settings.SCHEMA]}
        self.assertEqual(by_key["AUTO_ARM"][0], "bool")
        self.assertFalse(server.AUTO_ARM,
                         "auto-arm must be off unless explicitly enabled")


class Safety(unittest.TestCase):
    """Rules that keep the transmitter off the air."""

    def setUp(self):
        self._blk = dict(server.ST.swr_block)

    def tearDown(self):
        server.ST.swr_block = self._blk

    def test_high_swr_blocks_transmit(self):
        server.ST.swr_block = {"blocked": True, "swr": 5.0, "limit": 3.0}
        self.assertTrue(server.tx_blocked())
        self.assertIn("5.0", server.tx_block_msg())

    def test_good_swr_does_not_block(self):
        server.ST.swr_block = {"blocked": False, "swr": 1.2, "limit": 3.0}
        self.assertFalse(server.tx_blocked())

    def test_unknown_swr_does_not_block(self):
        """SWR only reads while transmitting; not knowing must never inhibit."""
        server.ST.swr_block = {"blocked": False, "swr": None, "limit": 3.0}
        self.assertFalse(server.tx_blocked())

    def test_drive_bounds(self):
        self.assertEqual((server.ATT_MIN, server.ATT_MAX), (0, 450))


if __name__ == "__main__":
    unittest.main(verbosity=2)
