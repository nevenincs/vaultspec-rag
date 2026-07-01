"""Unit tests for the shared path-domain classifier."""

from __future__ import annotations

from typing import ClassVar

import pytest

from .._domain import DOMAINS, NOISE_DOMAINS, classify_domain


class TestClassifyDomain:
    """`classify_domain` precedence and per-domain recognition."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_prod_default(self):
        assert classify_domain("src/vaultspec_rag/store.py") == "prod"
        assert classify_domain("lib/util.rs") == "prod"
        assert classify_domain("main.go") == "prod"

    def test_worktree_clone_wins_over_inner_src(self):
        # An inner src/ inside an agent worktree clone is still a clone.
        assert (
            classify_domain(".claude/worktrees/agent-abc/src/vaultspec_rag/store.py")
            == "worktree"
        )
        assert classify_domain(".git/worktrees/wt1/lib/core.py") == "worktree"

    def test_bare_worktrees_dir_without_known_parent_is_not_worktree(self):
        # A directory literally named worktrees but not under .claude/.git is
        # not treated as a clone tree.
        assert classify_domain("src/worktrees/manager.py") == "prod"

    def test_vendored(self):
        assert classify_domain("node_modules/left-pad/index.js") == "vendored"
        assert classify_domain("vendor/github.com/x/y.go") == "vendored"
        assert classify_domain(".venv/lib/site-packages/foo.py") == "vendored"
        assert classify_domain("dist/bundle.js") == "vendored"

    def test_generated(self):
        assert classify_domain("proto/service_pb2.py") == "generated"
        assert classify_domain("static/app.min.js") == "generated"
        assert classify_domain("__pycache__/mod.cpython-313.pyc") == "generated"
        assert classify_domain("src/api.generated.ts") == "generated"

    def test_tests(self):
        assert classify_domain("tests/test_store.py") == "tests"
        assert classify_domain("src/pkg/test_bar.py") == "tests"
        assert classify_domain("foo_test.go") == "tests"
        assert classify_domain("spec/parser_spec.rb") == "tests"
        assert classify_domain("conftest.py") == "tests"

    def test_locale(self):
        assert classify_domain("locales/en.yml") == "locale"
        assert classify_domain("locales/es.yml") == "locale"
        assert classify_domain("i18n/fr/messages.po") == "locale"
        assert classify_domain("translations/messages.de.po") == "locale"

    def test_docs(self):
        assert classify_domain("docs/guide.md") == "docs"
        assert classify_domain("README.md") == "docs"
        assert classify_domain("CHANGELOG.rst") == "docs"

    def test_precedence_vendored_over_tests(self):
        # A test file inside a vendored tree is vendored, not tests: the whole
        # tree is third-party noise.
        assert classify_domain("node_modules/pkg/tests/test_x.py") == "vendored"

    def test_data_file_without_lang_code_is_prod_not_locale(self):
        # A plain config/data file with an i18n-capable extension but no lang
        # code stays prod - we do not over-claim locale.
        assert classify_domain("pyproject.toml") == "prod"
        assert classify_domain("package.json") == "prod"
        assert classify_domain("config/settings.yaml") == "prod"

    def test_windows_separators_normalise(self):
        assert (
            classify_domain(r".claude\worktrees\agent-1\src\x.py") == "worktree"
        )
        assert classify_domain(r"tests\test_store.py") == "tests"

    def test_every_label_is_declared(self):
        labels = {
            classify_domain(p)
            for p in (
                "src/x.py",
                "tests/test_x.py",
                "docs/x.md",
                "locales/en.yml",
                "x_pb2.py",
                "node_modules/x.js",
                ".claude/worktrees/a/x.py",
            )
        }
        assert labels <= set(DOMAINS)
        assert "prod" not in NOISE_DOMAINS
        assert labels - {"prod"} <= NOISE_DOMAINS
