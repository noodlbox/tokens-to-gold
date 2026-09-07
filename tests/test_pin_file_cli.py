"""G5: `validate-pins --pin-file` — the flip gate's must-red, operable from the
CLI without editing the real pins.

e5 is "revert the pin to PENDING-RELEASE and watch --flip refuse". Before this
flag that meant editing the package's own PIN.toml or copying the whole tree, so
the one must-red that proves the gate can still fail was the awkward one to run.
A gate that passes once and cannot be made to fail again is not a gate.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ttg import cli
from ttg.pins import NOT_PUBLISHED, PENDING_RELEASE, PKG


class PinFileCliTest(unittest.TestCase):
    def _scratch(self, released_sha: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        dest = tmp / "PIN.toml"
        lines = (PKG / "PIN.toml").read_text().split("\n")
        # Match the section HEADER at line start, never a substring: the string
        # "[recert.released_binary]" also appears inside [recert.binary]'s
        # comment, and a `partition` on it rewrites a COMMENT while leaving the
        # real section untouched -- a scratch pin that silently still says
        # PENDING-RELEASE, i.e. a test that cannot tell filled from pending.
        start = lines.index("[recert.released_binary]")
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
            len(lines),
        )
        replacement = [
            'release_tag = "v1-2.3.18"',
            'asset_name = "noodl-eval-recert"',
            f'sha256 = "{released_sha}"',
        ]
        dest.write_text("\n".join(lines[: start + 1] + replacement + lines[end:]))
        return dest

    def _scratch_block(self, lines: list[str]) -> Path:
        """A scratch PIN whose [recert.released_binary] body is exactly `lines`."""
        import shutil as _shutil
        import tempfile as _tempfile

        tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, tmp, ignore_errors=True)
        dest = tmp / "PIN.toml"
        src = (PKG / "PIN.toml").read_text().split("\n")
        start = src.index("[recert.released_binary]")
        end = next(
            (i for i in range(start + 1, len(src)) if src[i].startswith("[")), len(src)
        )
        dest.write_text("\n".join(src[: start + 1] + lines + src[end:]))
        return dest

    def test_not_published_with_a_reason_passes_the_flip(self) -> None:
        pin = self._scratch_block(
            [f'state = "{NOT_PUBLISHED}"', 'reason = "internal tool; verifies offline"']
        )
        self.assertEqual(
            cli.main(["validate-pins", "--flip", "--pin-file", str(pin)]), 0
        )

    def test_not_published_WITHOUT_a_reason_is_refused(self) -> None:
        """MUST-RED: the contract forbids a SILENT absence. A declared state with
        no reason is a silent absence with a label on it."""
        pin = self._scratch_block([f'state = "{NOT_PUBLISHED}"'])
        self.assertEqual(
            cli.main(["validate-pins", "--flip", "--pin-file", str(pin)]), 2
        )

    def test_the_committed_pin_declares_not_published_with_a_reason(self) -> None:
        """The shipped state itself: --flip passes on the real PIN.toml."""
        self.assertEqual(cli.main(["validate-pins", "--flip"]), 0)

    def test_pending_sentinel_still_refuses_the_flip(self) -> None:
        """MUST-RED: the gate must return to a refusal when the pin is reverted."""
        pin = self._scratch(PENDING_RELEASE)
        self.assertEqual(cli.main(["validate-pins", "--flip", "--pin-file", str(pin)]), 2)

    def test_filled_release_passes_the_flip(self) -> None:
        pin = self._scratch("a" * 64)
        self.assertEqual(cli.main(["validate-pins", "--flip", "--pin-file", str(pin)]), 0)

    def test_measurement_gate_is_independent_of_the_release_gate(self) -> None:
        """The two sentinels are two lifecycles: a pending RELEASE must not make
        the MEASUREMENT gate fail, or filling one would silently satisfy the
        other."""
        pin = self._scratch(PENDING_RELEASE)
        self.assertEqual(cli.main(["validate-pins", "--pin-file", str(pin)]), 0)

    def test_a_malformed_released_sha_is_refused(self) -> None:
        pin = self._scratch("not-a-digest")
        self.assertEqual(cli.main(["validate-pins", "--flip", "--pin-file", str(pin)]), 2)

    def test_default_path_still_reads_the_packages_own_pins(self) -> None:
        self.assertEqual(cli.main(["validate-pins"]), 0)


if __name__ == "__main__":
    unittest.main()
