"""onus.scrub: run-to-run values replaced by tokens numbered by value, and nothing else touched."""

import functools
import pathlib
import re
import types
import unittest

import onus.scrub
from onus.scrub import Scrubber, chain, hex_ids, iso_dates, iso_timestamps, paths, pattern, redactor, uuids

SHA_A = "3f2a9c0d1e" * 4
SHA_B = "9b77e1f004" * 4
UUID_A = "0f8fad5b-d9cb-469f-a165-70867728950e"
UUID_B = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


def shout(text: str) -> str:
    return text.upper()


class NumberingTest(unittest.TestCase):
    """What every numbered scrubber shares: one number per distinct value, in order of first appearance."""

    def test_equal_values_share_a_number_and_distinct_ones_do_not(self):
        text = f"run {SHA_A} started, run {SHA_B} retried, run {SHA_A} done"
        self.assertEqual(hex_ids(40)(text), "run <hex-1> started, run <hex-2> retried, run <hex-1> done")

    def test_numbers_follow_first_appearance_not_the_values_order(self):
        self.assertEqual(
            iso_dates()("2026-03-01 then 2026-01-08 then 2026-03-01"), "<date-1> then <date-2> then <date-1>"
        )

    def test_each_text_is_numbered_from_one(self):
        scrubber = iso_dates()
        self.assertEqual(scrubber("2026-03-01"), "<date-1>")
        self.assertEqual(scrubber("2026-01-08"), "<date-1>")

    def test_a_scrubbed_text_scrubs_to_itself(self):
        scrubber = chain(iso_timestamps(), iso_dates(), uuids(), hex_ids(40), paths({"/srv/app": "app"}))
        once = scrubber(f"{UUID_A} at 2026-01-08T11:00:00Z on 2026-01-08 in /srv/app/out is {SHA_A}")
        self.assertEqual(once, "<uuid-1> at <timestamp-1> on <date-1> in <app>/out is <hex-1>")
        self.assertEqual(scrubber(once), once)

    def test_a_text_with_nothing_to_scrub_is_returned_as_it_was(self):
        text = "p = 0.0443 at n = 100; 12 wins, 3 losses\n"
        for scrubber in (iso_dates(), iso_timestamps(), uuids(), hex_ids(8, 40), paths({"/srv/app": "app"})):
            with self.subTest(scrubber=scrubber.name):
                self.assertEqual(scrubber(text), text)

    def test_only_a_text_is_scrubbed(self):
        for scrubber in (iso_dates(), chain(uuids()), redactor(shout)):
            with self.subTest(scrubber=scrubber.name), self.assertRaisesRegex(TypeError, "scrubs a text, not bytes"):
                scrubber(b"2026-01-08")  # type: ignore[arg-type]


class DatesTest(unittest.TestCase):
    def test_only_a_real_date_is_replaced(self):
        self.assertEqual(iso_dates()("2026-02-28, 2026-02-30, 2026-13-01"), "<date-1>, 2026-02-30, 2026-13-01")

    def test_a_date_inside_a_longer_number_or_word_stays(self):
        for text in ("12026-01-08", "2026-01-081", "v2026-01-08", "2026-01-08a"):
            with self.subTest(text=text):
                self.assertEqual(iso_dates()(text), text)

    def test_punctuation_round_a_date_does_not_hide_it(self):
        self.assertEqual(iso_dates()("(2026-01-08), run-2026-01-08-b."), "(<date-1>), run-<date-1>-b.")

    def test_the_date_of_a_timestamp_is_left_for_the_timestamp_scrubber(self):
        text = "2026-01-08T11:00:00Z and 2026-01-08 11:00 on 2026-01-08"
        self.assertEqual(iso_dates()(text), "2026-01-08T11:00:00Z and 2026-01-08 11:00 on <date-1>")
        for order in ((iso_dates(), iso_timestamps()), (iso_timestamps(), iso_dates())):
            with self.subTest(first=order[0].name):
                self.assertEqual(chain(*order)(text), "<timestamp-1> and <timestamp-2> on <date-1>")


class TimestampsTest(unittest.TestCase):
    def test_each_written_form_is_replaced_whole(self):
        forms = (
            "2026-01-08T11:00",
            "2026-01-08 11:00",
            "2026-01-08T11:00:05",
            "2026-01-08T11:00:05.5",
            "2026-01-08T11:00:05.123456",
            "2026-01-08T11:00:05.123456789",
            "2026-01-08T11:00:05Z",
            "2026-01-08T11:00:05+00:00",
            "2026-01-08T11:00:05.25-08:00",
        )
        for form in forms:
            with self.subTest(form=form):
                self.assertEqual(iso_timestamps()(f"at {form}."), "at <timestamp-1>.")

    def test_only_a_real_moment_is_replaced(self):
        for text in ("2026-01-08T25:00", "2026-02-30T11:00:00Z", "2026-01-08T11:61"):
            with self.subTest(text=text):
                self.assertEqual(iso_timestamps()(text), text)

    def test_timestamps_written_differently_are_different_values(self):
        text = "2026-01-08T11:00:00Z, 2026-01-08T11:00:00+00:00, 2026-01-08T11:00:00Z"
        self.assertEqual(iso_timestamps()(text), "<timestamp-1>, <timestamp-2>, <timestamp-1>")

    def test_a_bare_date_is_not_a_timestamp(self):
        self.assertEqual(iso_timestamps()("on 2026-01-08 at noon"), "on 2026-01-08 at noon")

    def test_a_timestamp_inside_a_longer_word_stays(self):
        for text in ("x2026-01-08T11:00", "2026-01-08T11:00x", "2026-01-08T11:001"):
            with self.subTest(text=text):
                self.assertEqual(iso_timestamps()(text), text)


class UuidsTest(unittest.TestCase):
    def test_a_uuid_is_replaced_and_its_case_does_not_make_it_another(self):
        text = f"{UUID_A} {UUID_B} {UUID_A.upper()}"
        self.assertEqual(uuids()(text), "<uuid-1> <uuid-2> <uuid-1>")

    def test_a_shape_that_is_not_a_uuid_stays(self):
        short = UUID_A[:-1]
        for text in (short, UUID_A + "0", "a" + UUID_A, UUID_A.replace("-", ""), UUID_A.replace("f", "g")):
            with self.subTest(text=text):
                self.assertEqual(uuids()(text), text)


class HexIdsTest(unittest.TestCase):
    def test_only_a_run_of_a_listed_length_is_replaced(self):
        sha256 = "ab" * 32
        text = f"{SHA_A} {sha256} {SHA_A[:39]} {SHA_A}0"
        self.assertEqual(hex_ids(40, 64)(text), f"<hex-1> <hex-2> {SHA_A[:39]} {SHA_A}0")
        self.assertEqual(hex_ids(40)(text), f"<hex-1> {sha256} {SHA_A[:39]} {SHA_A}0")

    def test_a_run_inside_a_longer_word_stays(self):
        for text in (f"x{SHA_A}", f"{SHA_A}z", f"{SHA_A}g"):
            with self.subTest(text=text):
                self.assertEqual(hex_ids(40)(text), text)

    def test_a_number_is_never_replaced(self):
        # Digits alone, at a listed length: a count, a numerator, or the digits of an exact p-value.
        text = "n = 12345678; p = 6004799503160661/18014398509481984; 0.6666070179300212860107421875"
        self.assertEqual(hex_ids(8, 16, 17, 28)(text), text)

    def test_case_does_not_make_two_ids(self):
        self.assertEqual(hex_ids(40)(f"{SHA_A} {SHA_A.upper()}"), "<hex-1> <hex-1>")

    def test_the_lengths_are_required_and_at_least_eight(self):
        for lengths in ((), (7,), (40, 7), (40.0,), ("40",), (True,)):
            with self.subTest(lengths=lengths), self.assertRaisesRegex(ValueError, "each an int of at least 8"):
                hex_ids(*lengths)
        self.assertEqual(hex_ids(8)("deadbeef facade"), "<hex-1> facade")

    def test_its_name_lists_its_lengths_in_order(self):
        self.assertEqual(hex_ids(64, 40, 64).name, "hex_ids(40, 64)")


class PatternTest(unittest.TestCase):
    def test_each_match_is_replaced_and_numbered_by_its_text(self):
        scrubber = pattern(r"run-[0-9a-f]{6}", "run")
        self.assertEqual(scrubber("run-00ab12 then run-ffffff then run-00ab12"), "<run-1> then <run-2> then <run-1>")
        self.assertEqual(scrubber.name, "pattern('run-[0-9a-f]{6}', 'run')")

    def test_a_name_that_cannot_stand_in_a_token_is_refused(self):
        for name in ("", "Run", "1run", "run-id", "run id", "<run>", "run\n", None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "a token's name is a lower-case letter"):
                pattern("x", name)  # type: ignore[arg-type]

    def test_a_regex_that_matches_nothing_at_all_is_refused_when_it_does(self):
        scrubber = pattern("x*", "x")
        with self.assertRaisesRegex(ValueError, "matched an empty text"):
            scrubber("abc")

    def test_the_regex_is_a_string_that_compiles(self):
        with self.assertRaisesRegex(TypeError, "takes the regex as a string"):
            pattern(re.compile("x"), "x")  # type: ignore[arg-type]
        with self.assertRaises(re.error):
            pattern("(", "x")


class PathsTest(unittest.TestCase):
    def test_a_path_is_replaced_by_its_name_wherever_it_stands_whole(self):
        scrubber = paths({"/srv/app": "app"})
        self.assertEqual(
            scrubber("in /srv/app, /srv/app/out/a.md and '/srv/app'."), "in <app>, <app>/out/a.md and '<app>'."
        )
        self.assertEqual(scrubber("wrote /srv/app."), "wrote <app>.")

    def test_a_folder_whose_name_only_starts_alike_stays(self):
        scrubber = paths({"/srv/app": "app"})
        for text in ("/srv/app2", "/srv/app-old/x", "/srv/app_b", "/srv/app.bak", "/srv/application"):
            with self.subTest(text=text):
                self.assertEqual(scrubber(text), text)

    def test_the_longest_path_wins_and_the_shorter_still_applies_elsewhere(self):
        scrubber = paths({"/srv/app": "app", "/srv/app/cache": "cache", "/srv": "srv"})
        self.assertEqual(
            scrubber("/srv/app/cache/x /srv/app/y /srv/z /srv/app2"), "<cache>/x <app>/y <srv>/z <srv>/app2"
        )

    def test_both_macos_spellings_of_a_temporary_folder_are_replaced(self):
        for given in ("/var/folders/ab/T", "/private/var/folders/ab/T"):
            with self.subTest(given=given):
                scrubber = paths({given: "tmp"})
                self.assertEqual(scrubber("/var/folders/ab/T/x and /private/var/folders/ab/T/x"), "<tmp>/x and <tmp>/x")
        self.assertEqual(paths({"/tmp/w": "w"})("/private/tmp/w/x"), "<w>/x")
        self.assertEqual(paths({"/private/etc": "etc"})("/etc/hosts"), "<etc>/hosts")
        self.assertEqual(paths({"/var": "var"})("/private/var/x /var/x"), "<var>/x <var>/x")

    def test_no_other_folder_gains_a_private_spelling(self):
        self.assertEqual(paths({"/srv/app": "app"})("/private/srv/app"), "/private<app>")
        self.assertEqual(paths({"/variable/x": "x"})("/private/variable/x"), "/private<x>")
        self.assertEqual(paths({"/private/variable/x": "x"})("/variable/x"), "/variable/x")

    def test_a_trailing_slash_and_a_pathlike_are_read_as_the_folder(self):
        self.assertEqual(paths({"/srv/app/": "app"})("/srv/app/x"), "<app>/x")
        self.assertEqual(paths({pathlib.PurePosixPath("/srv/app"): "app"})("/srv/app/x"), "<app>/x")

    def test_two_paths_may_share_a_name_and_one_path_may_not_have_two(self):
        self.assertEqual(paths({"/srv/a": "work", "/srv/b": "work"})("/srv/a /srv/b"), "<work> <work>")
        self.assertEqual(paths({"/var/x": "x", "/private/var/x": "x"})("/var/x"), "<x>")
        with self.assertRaisesRegex(ValueError, "'/private/var/x' is given two names, 'a' and 'b'"):
            paths({"/var/x": "a", "/private/var/x": "b"})

    def test_what_is_not_a_mapping_of_absolute_paths_to_names_is_refused(self):
        with self.assertRaisesRegex(ValueError, "at least one path"):
            paths({})
        for path in ("srv/app", "", "/", "//", "~/app"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "absolute paths below the root"):
                paths({path: "app"})
        with self.assertRaisesRegex(ValueError, "a token's name"):
            paths({"/srv/app": "App"})
        with self.assertRaisesRegex(TypeError, "a mapping from each path to its name, not list"):
            paths([("/srv/app", "app")])  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "each path as text, not bytes"):
            paths({pathlib.PurePosixPath("/srv/app").__fspath__().encode(): "app"})  # type: ignore[dict-item]

    def test_its_name_lists_every_spelling_it_replaces(self):
        self.assertEqual(paths({"/var/x": "x"}).name, "paths({'/private/var/x': 'x', '/var/x': 'x'})")

    def test_a_regex_character_in_a_path_is_read_as_itself(self):
        self.assertEqual(paths({"/srv/a+b (1)": "a"})("/srv/a+b (1)/x /srv/aab (1)"), "<a>/x /srv/aab (1)")


class RedactorTest(unittest.TestCase):
    def test_it_runs_the_function_and_is_named_after_it(self):
        scrubber = redactor(shout)
        self.assertEqual(scrubber("quiet"), "QUIET")
        self.assertEqual(scrubber.name, "redactor(tests.test_scrub.shout)")

    def test_a_function_that_returns_no_text_is_refused_when_it_runs(self):
        scrubber = redactor(len)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, r"redactor\(builtins.len\) must return a text, not int"):
            scrubber("abc")

    def test_what_has_no_name_to_record_is_refused(self):
        named_but_not_callable = types.SimpleNamespace(__module__="tests.test_scrub", __qualname__="shout")
        for nameless in (functools.partial(shout), "shout", None, named_but_not_callable):
            with self.subTest(nameless=nameless), self.assertRaisesRegex(TypeError, "takes a named function"):
                redactor(nameless)  # type: ignore[arg-type]


class ChainTest(unittest.TestCase):
    def test_each_scrubber_reads_what_the_one_before_left(self):
        first_then_shout = chain(pattern("a", "first"), redactor(shout))
        shout_then_first = chain(redactor(shout), pattern("a", "first"))
        self.assertEqual(first_then_shout("a b"), "<FIRST-1> B")
        self.assertEqual(shout_then_first("a b"), "A B")

    def test_its_name_lists_its_scrubbers_in_order(self):
        self.assertEqual(chain(iso_dates(), uuids()).name, "chain(iso_dates, uuids)")
        self.assertEqual(chain(uuids(), chain(iso_dates())).name, "chain(uuids, chain(iso_dates))")

    def test_it_needs_a_scrubber_and_takes_nothing_else(self):
        with self.assertRaisesRegex(ValueError, "at least one scrubber"):
            chain()
        with self.assertRaisesRegex(TypeError, "wrap a plain function with redactor"):
            chain(iso_dates(), shout)  # type: ignore[arg-type]


class SurfaceTest(unittest.TestCase):
    def test_no_scrubber_for_numbers_or_personal_data_ships(self):
        self.assertEqual(
            sorted(onus.scrub.__all__),
            ["Scrubber", "chain", "hex_ids", "iso_dates", "iso_timestamps", "paths", "pattern", "redactor", "uuids"],
        )

    def test_a_scrubber_cannot_be_renamed_once_built(self):
        scrubber = iso_dates()
        self.assertIsInstance(scrubber, Scrubber)
        with self.assertRaises(AttributeError):
            scrubber.name = "other"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
