"""In-memory vault for the offline tests: no network, no trip2g, no notes on disk.

The shipped scripts reach the vault through five module-level functions and one
`gql`. The stub swaps those out and makes `gql` raise, so a test that reaches
the network fails loudly instead of hanging on a socket. Nothing under
packaging/ imports this file; the direction is tests -> scripts only.
"""
import contextlib
import importlib.util
import io
import re
import sys


def load(path, name):
    """Import a shipped script as a module without touching the packaged tree."""
    sys.dont_write_bytecode = True  # no __pycache__ inside packaging/
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _no_network(*a, **k):
    raise AssertionError('a test reached the network: gql() was called')


class Vault(dict):
    """path -> content. `like` is the SQL LIKE that notePaths takes."""

    def list_paths(self, like):
        rx = re.compile('^' + '.*'.join(re.escape(x) for x in like.split('%')) + '$')
        return {p: 'h' for p in self if rx.match(p)}

    def read_note(self, path):
        return (self.get(path), 'h' if path in self else None)

    def write_note(self, path, content, expected_hash=''):
        # Create-only when the hash is empty, like the real mutation. A given
        # hash is not checked here: the tests do not cover a losing race.
        if expected_hash == '' and path in self:
            return 'exists'
        self[path] = content
        return 'ok'

    def hide_note(self, path):
        self.pop(path, None)
        return True

    def install(self, *mods):
        for m in mods:
            m.list_paths, m.read_note, m.write_note = self.list_paths, self.read_note, self.write_note
            if hasattr(m, 'hide_note'):
                m.hide_note = self.hide_note
            m.gql = _no_network
        return self


def run(mod, argv):
    """Run a script's main() with argv; returns (stdout, exit code)."""
    buf, code, old = io.StringIO(), 0, sys.argv
    sys.argv = list(argv)
    try:
        with contextlib.redirect_stdout(buf):
            mod.main()
    except SystemExit as e:
        code = e.code or 0
    finally:
        sys.argv = old
    return buf.getvalue().rstrip('\n'), code
