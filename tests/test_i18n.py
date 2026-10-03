"""Hindi and English must stay in step: same keys, same {placeholders}."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from i18n import EN, HI


def test_both_languages_have_the_same_keys():
    assert set(EN) == set(HI)


def test_placeholders_match_so_no_message_crashes_in_hindi():
    holes = lambda s: sorted(re.findall(r"{(\w+)}", s))
    for k in EN:
        assert holes(EN[k]) == holes(HI[k]), k
