from __future__ import annotations

import unittest
from unittest.mock import patch

from arch_env import tui


class TuiTests(unittest.TestCase):
    def test_configure_colors_uses_default_backgrounds(self) -> None:
        with (
            patch("arch_env.tui.curses.has_colors", return_value=True),
            patch("arch_env.tui.curses.start_color") as start_color,
            patch("arch_env.tui.curses.use_default_colors") as use_default_colors,
            patch("arch_env.tui.curses.init_pair") as init_pair,
            patch("arch_env.tui.curses.color_pair", side_effect=lambda pair: pair * 100),
        ):
            tui._configure_colors()

        start_color.assert_called_once()
        use_default_colors.assert_called_once()
        init_pair.assert_any_call(1, tui.curses.COLOR_CYAN, -1)
        init_pair.assert_any_call(7, tui.curses.COLOR_WHITE, -1)
        self.assertEqual(tui.Palette.title, 100)
        self.assertEqual(tui.Palette.label, 700)

    def test_configure_colors_noops_without_color_support(self) -> None:
        with (
            patch("arch_env.tui.curses.has_colors", return_value=False),
            patch("arch_env.tui.curses.start_color") as start_color,
        ):
            tui._configure_colors()

        start_color.assert_not_called()


if __name__ == "__main__":
    unittest.main()
