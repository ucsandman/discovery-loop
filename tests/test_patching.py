"""Edit-block parsing and application, including one real Opus response captured on 2026-09-20."""

from pathlib import Path

import patching


FIXTURES = Path(__file__).parent / "fixtures" / "diff-mode"

SOURCE = "alpha = 1\nbeta = 2\ngamma = 3\n"


def _block(search, replace):
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


def test_one_block_replaces_exactly_its_own_lines():
    patched, error = patching.apply_blocks(SOURCE, _block("beta = 2", "beta = 20"))
    assert error is None
    assert patched == "alpha = 1\nbeta = 20\ngamma = 3\n"


def test_blocks_apply_in_order_and_may_add_lines():
    text = _block("alpha = 1", "alpha = 1\ndelta = 4") + "\n\n" + _block("gamma = 3", "gamma = 30")
    patched, error = patching.apply_blocks(SOURCE, text)
    assert error is None
    assert patched == "alpha = 1\ndelta = 4\nbeta = 2\ngamma = 30\n"


def test_prose_around_the_blocks_is_ignored():
    text = "IDEA: [kind: tuning] raise beta\n\n" + _block("beta = 2", "beta = 20") + "\n\nThat is the change."
    patched, error = patching.apply_blocks(SOURCE, text)
    assert error is None and "beta = 20" in patched


def test_a_response_with_no_block_is_refused():
    patched, error = patching.apply_blocks(SOURCE, "```python\nalpha = 9\n```")
    assert patched is None and error == "response contained no SEARCH/REPLACE block"


def test_a_search_that_matches_nothing_names_what_it_looked_for():
    patched, error = patching.apply_blocks(SOURCE, _block("epsilon = 5", "epsilon = 50"))
    assert patched is None
    assert "did not match the file" in error and "epsilon = 5" in error


def test_an_ambiguous_search_is_refused_rather_than_guessed():
    source = "value = 1\nvalue = 1\n"
    patched, error = patching.apply_blocks(source, _block("value = 1", "value = 2"))
    assert patched is None
    assert "matched 2 places" in error


def test_an_empty_search_section_is_refused():
    patched, error = patching.apply_blocks(SOURCE, _block("   ", "delta = 4"))
    assert patched is None and "empty SEARCH section" in error


def test_a_no_op_edit_is_refused():
    patched, error = patching.apply_blocks(SOURCE, _block("beta = 2", "beta = 2"))
    assert patched is None and error == "edit blocks left the file unchanged"


def test_windows_line_endings_on_either_side_still_match():
    text = _block("beta = 2", "beta = 20").replace("\n", "\r\n")
    patched, error = patching.apply_blocks(SOURCE.replace("\n", "\r\n"), text)
    assert error is None and patched == "alpha = 1\nbeta = 20\ngamma = 3\n"


def test_more_blocks_than_the_limit_are_refused():
    text = "\n\n".join(_block(f"line{index}", f"line{index}x") for index in range(patching.MAX_BLOCKS + 1))
    patched, error = patching.apply_blocks(SOURCE, text)
    assert patched is None and "the limit is" in error


def test_an_empty_source_is_refused():
    patched, error = patching.apply_blocks("", _block("a", "b"))
    assert patched is None and error == "no incumbent source to edit"


def test_the_real_opus_response_applies_and_the_result_compiles():
    """Captured 2026-09-20 from one claude-opus-5 call in diff mode ($0.20, two blocks)."""
    source = (FIXTURES / "incumbent.py").read_text(encoding="utf-8")
    response = (FIXTURES / "opus-response.txt").read_text(encoding="utf-8")
    assert len(patching.parse_blocks(response)) == 2
    patched, error = patching.apply_blocks(source, response)
    assert error is None
    assert patched != source
    compile(patched, "patched.py", "exec")
    # The response is a fraction of the file it edits: that is the whole point of the mode.
    assert len(response) < len(source)
