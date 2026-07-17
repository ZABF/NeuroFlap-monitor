import math
import unittest

from ui.curve_expression import (
    CurveExpressionParser,
    clip_scalar,
    clip_series,
    expression_validation_errors,
    resolve_clip_bounds,
)


class CurveExpressionClipTest(unittest.TestCase):
    def test_parser_accepts_symmetric_clip(self):
        ast = CurveExpressionParser("clip([AttRoll], +-100)").parse()

        self.assertEqual(ast[0:2], ("call", "clip"))
        self.assertEqual(len(ast[2]), 2)
        self.assertEqual(expression_validation_errors(ast), [])

    def test_parser_accepts_explicit_bounds(self):
        ast = CurveExpressionParser("clip([AttRoll], -20, 30)").parse()

        self.assertEqual(len(ast[2]), 3)
        self.assertEqual(expression_validation_errors(ast), [])

    def test_validation_rejects_wrong_arity(self):
        ast = CurveExpressionParser("clip([AttRoll])").parse()

        self.assertEqual(expression_validation_errors(ast), ["clip() expects 2 or 3 arguments"])

    def test_symmetric_bounds_use_absolute_limit(self):
        self.assertEqual(resolve_clip_bounds(20), (-20.0, 20.0))
        self.assertEqual(resolve_clip_bounds(-20), (-20.0, 20.0))

    def test_explicit_bounds_reject_reversed_or_non_finite_values(self):
        self.assertEqual(resolve_clip_bounds(-20, 30), (-20.0, 30.0))
        self.assertIsNone(resolve_clip_bounds(30, -20))
        self.assertIsNone(resolve_clip_bounds(math.inf))

    def test_clip_scalar_clamps_both_sides(self):
        self.assertEqual(clip_scalar(-25, -20, 30), -20.0)
        self.assertEqual(clip_scalar(10, -20, 30), 10.0)
        self.assertEqual(clip_scalar(35, -20, 30), 30.0)

    def test_clip_series_preserves_valid_timestamps_and_drops_invalid_samples(self):
        ts, vs = clip_series(
            [0, 1, 2, 3, math.inf],
            [-25, 10, 35, math.nan, 5],
            -20,
            30,
        )

        self.assertEqual(ts, [0.0, 1.0, 2.0])
        self.assertEqual(vs, [-20.0, 10.0, 30.0])


if __name__ == "__main__":
    unittest.main()
