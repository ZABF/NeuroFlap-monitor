import os
import unittest

from ui.curve_expression import CurveExpressionParser
from ui.curve_state import ActiveDataSource, resolve_derived_health


def _spec(expression):
    return {
        "kind": "expr",
        "expr": expression,
        "ast": CurveExpressionParser(expression).parse(),
    }


class ActiveDataSourceTest(unittest.TestCase):
    def test_replay_label_uses_basename_and_keeps_full_path(self):
        source = ActiveDataSource.replay("./captures/flight.csv")

        self.assertEqual(source.label, "Source: Replay flight.csv")
        self.assertEqual(source.detail, os.path.abspath("./captures/flight.csv"))

    def test_live_label_contains_endpoint(self):
        source = ActiveDataSource.live("192.168.4.1", 28080)

        self.assertEqual(source.label, "Source: Live 192.168.4.1:28080")


class DerivedCurveHealthTest(unittest.TestCase):
    def test_same_raw_names_keep_derived_valid(self):
        specs = {"sum": _spec("[a] + [b]")}

        health = resolve_derived_health(specs, {"a", "b"})

        self.assertTrue(health["sum"].valid)

    def test_missing_dependency_invalidates_and_later_recovers(self):
        specs = {"sum": _spec("[a] + [b]")}

        missing = resolve_derived_health(specs, {"a"})
        restored = resolve_derived_health(specs, {"a", "b"})

        self.assertEqual(missing["sum"].missing_refs, ("b",))
        self.assertFalse(missing["sum"].valid)
        self.assertTrue(restored["sum"].valid)

    def test_nested_derived_propagates_missing_raw_dependency(self):
        specs = {
            "sum": _spec("[a] + [b]"),
            "scaled": _spec("[sum] * 2"),
        }

        health = resolve_derived_health(specs, {"a"})

        self.assertEqual(health["sum"].missing_refs, ("b",))
        self.assertEqual(health["scaled"].missing_refs, ("b",))

    def test_raw_name_collision_is_reported_without_dropping_spec(self):
        specs = {"sum": _spec("[a] + 1")}

        health = resolve_derived_health(specs, {"a", "sum"})

        self.assertEqual(health["sum"].conflicts, ("sum",))
        self.assertIn("Name conflict: sum", health["sum"].message)


if __name__ == "__main__":
    unittest.main()
