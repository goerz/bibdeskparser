"""Replay the ``console`` examples from the documentation.

The how-to and CLI-reference pages illustrate the command-line tool
with ``console`` code fences: ``$ bibdeskparser ...`` commands followed
by their expected output. The tests here extract every such command and
replay it through click's `CliRunner` in a sandbox copy of the example
database, so that the documented invocations and their output cannot
drift from the actual behavior of the CLI.

A fence preceded by an ``<!-- notest -->`` HTML comment (invisible in
the rendered documentation) is excluded; this marks purely illustrative
examples, e.g. ones referencing files that do not exist. Commands that
need network access, open an interactive editor, or pipe through
non-`bibdeskparser` programs are detected and skipped automatically.

Expected output is compared like a doctest, so ``...`` in the
documented output matches anything (`doctest.ELLIPSIS`). A command with
no output shown is only checked to succeed.
"""

import doctest
import re
import shlex
import shutil
from pathlib import Path
from typing import NamedTuple

import pytest
from click.testing import CliRunner

import bibdeskparser.config as config
from bibdeskparser.cli import main

TESTS_DIR = Path(__file__).parent
DOCS_DIR = TESTS_DIR.parent / "docs" / "sources"

#: The documentation pages under test, mapped to how their blocks run:
#: "script" pages form one narrative (all blocks run in order in one
#: sandbox, as one test); "blocks" pages are independent illustrations
#: (each block runs in a fresh sandbox, as its own test).
PAGES = {"howto.md": "script", "cli.md": "blocks"}

#: Directories (relative to `tests/`) copied into each sandbox.
SANDBOX_DIRS = ("Refs", "test_cli_fail_checks")

#: Subcommands that contact online services (skipped automatically).
NETWORK_COMMANDS = {"add", "add_abstract", "add_preprint", "add_doi"}

NOTEST_MARKER = "<!-- notest -->"

HEREDOC_RX = re.compile(r"<<\s*'?(\w+)'?\s*$")
SUBST_RX = re.compile(r"\$\(([^()]*)\)")

_CHECKER = doctest.OutputChecker()


class Step(NamedTuple):
    lineno: int
    command: str  # the full shell line, continuation lines joined
    stdin: "str | None"  # heredoc body, if any
    expected: str  # documented output, up to the next ``$`` prompt


class Block(NamedTuple):
    page: str
    lineno: int
    steps: "list[Step]"


@pytest.fixture(autouse=True)
def _reset_config(tmp_path, monkeypatch):
    """Reset the process-global configuration around every test here
    (as in `test_cli.py`), and point `$XDG_CONFIG_HOME` at an empty
    directory so that a real user-level `bibdeskparser.toml` can never
    leak into a test."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    config.active.reset()
    yield
    config.active.reset()


def _parse_console_blocks(path):
    """Extract the commands from the ``console`` fences of `path`.

    Within a fence, a line starting with ``$ `` begins a command; a
    trailing backslash joins the next line; a heredoc (``<< 'EOF'``)
    consumes lines up to the delimiter as the command's stdin; every
    other line is expected output of the preceding command.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != "```console":
            i += 1
            continue
        notest = i > 0 and lines[i - 1].strip() == NOTEST_MARKER
        block_lineno = i + 1
        steps = []
        i += 1
        while lines[i].strip() != "```":
            if lines[i].startswith("$ "):
                lineno = i + 1
                command = lines[i][2:]
                while command.endswith("\\"):
                    i += 1
                    command = command[:-1].rstrip() + " " + lines[i].strip()
                stdin = None
                heredoc = HEREDOC_RX.search(command)
                if heredoc:
                    command = command[: heredoc.start()].rstrip()
                    body = []
                    i += 1
                    while lines[i] != heredoc.group(1):
                        body.append(lines[i])
                        i += 1
                    stdin = "\n".join(body) + "\n"
                steps.append(Step(lineno, command, stdin, ""))
            else:
                assert steps, f"{path.name}:{i + 1}: output before command"
                steps[-1] = steps[-1]._replace(
                    expected=steps[-1].expected + lines[i] + "\n"
                )
            i += 1
        if not notest:
            blocks.append(Block(path.name, block_lineno, steps))
        i += 1
    return blocks


def _skip_reason(command):
    """Why `command` cannot run under `CliRunner`, or None if it can."""
    for stage in command.split("|"):
        argv = shlex.split(stage, comments=True)
        if argv[0] != "bibdeskparser":
            return f"pipeline stage {argv[0]!r}"
        subcommand = argv[1] if len(argv) > 1 else ""
        if subcommand in NETWORK_COMMANDS:
            return f"{subcommand!r} needs network access"
        if subcommand == "import" and "--url" in argv:
            return "'import --url' needs network access"
        if subcommand in ("edit", "edit_strings") and "--stdin" not in argv:
            return f"{subcommand!r} would open an interactive editor"
    return None


def _make_runner():
    try:
        # click < 8.2 mixes stderr into stdout unless told otherwise
        return CliRunner(mix_stderr=False)
    except TypeError:  # click >= 8.2 always captures stderr separately
        return CliRunner()


def _run_command(runner, command, stdin, ctx):
    """Run one shell line; return its stdout, or None if skipped.

    Handles one level of ``$(...)`` command substitution and pipelines
    whose every stage is a `bibdeskparser` invocation.
    """
    if _skip_reason(command) is not None:
        return None
    while (match := SUBST_RX.search(command)) is not None:
        inner = _run_command(runner, match.group(1), None, ctx)
        assert inner is not None, f"{ctx}: skipped command substitution"
        command = (
            command[: match.start()] + inner.strip() + command[match.end() :]
        )
    data = stdin
    for stage in command.split("|"):
        argv = shlex.split(stage, comments=True)
        result = runner.invoke(
            main, argv[1:], input=data, catch_exceptions=False
        )
        # `check` reports found problems via exit code 1 by design
        allowed = {0, 1} if argv[1] == "check" else {0}
        assert result.exit_code in allowed, (
            f"{ctx}\n$ {command}\n[exit code {result.exit_code}]\n"
            + result.output
            + result.stderr
        )
        data = result.stdout
    return data


def _replay(runner, page, step):
    ctx = f"{page}:{step.lineno}"
    got = _run_command(runner, step.command, step.stdin, ctx)
    if got is None or not step.expected:
        return
    assert _CHECKER.check_output(step.expected, got, doctest.ELLIPSIS), (
        f"{ctx}\n$ {step.command}\n"
        f"--- documented ---\n{step.expected}--- actual ---\n{got}"
    )


def _params():
    params = []
    for page, mode in PAGES.items():
        blocks = _parse_console_blocks(DOCS_DIR / page)
        assert blocks, f"no testable console blocks in {page}"
        if mode == "script":
            params.append(pytest.param(blocks, id=page))
        else:
            params.extend(
                pytest.param([block], id=f"{page}:{block.lineno}")
                for block in blocks
            )
    return params


@pytest.mark.parametrize("blocks", _params())
def test_console_examples(blocks, tmp_path, monkeypatch):
    """The documented console commands run, and print what they show."""
    for name in SANDBOX_DIRS:
        shutil.copytree(TESTS_DIR / name, tmp_path / "tests" / name)
    monkeypatch.chdir(tmp_path)
    runner = _make_runner()
    for block in blocks:
        for step in block.steps:
            _replay(runner, block.page, step)
