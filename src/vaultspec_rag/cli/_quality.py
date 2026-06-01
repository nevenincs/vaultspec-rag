"""``quality`` command: needle-based precision probes on a synthetic vault."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..embeddings import EmbeddingModel
from ..indexer import VaultIndexer
from ..search import VaultSearcher
from ._app import app
from ._gpu_errors import _handle_gpu_error
from ._store import _open_vault_store


@app.command("quality")
def handle_quality() -> None:
    """Run quality-scoring probes against a synthetic test corpus.

    Generates a temporary synthetic vault, indexes it, runs
    needle-based precision probes, and reports results. Exits 1
    if fewer than 75% of probes pass.

    This is a developer regression tool -- not tied to a specific
    user vault.

    Raises:
        typer.Exit: On GPU errors or when precision drops below 75%.
    """
    import tempfile

    from ..synthetic import build_synthetic_vault

    with tempfile.TemporaryDirectory(prefix="vaultspec-quality-") as _tmp:
        root = Path(_tmp)
        manifest = build_synthetic_vault(root, n_docs=24, seed=42)

        try:
            model = EmbeddingModel()
        except (ImportError, RuntimeError) as e:
            _handle_gpu_error(e)

        store = _open_vault_store(root)

        try:
            from ..progress import NullProgressReporter

            indexer = VaultIndexer(root, model, store)
            with _cli.console.status("[bold green]Indexing synthetic corpus..."):
                indexer.full_index(reporter=NullProgressReporter())

            searcher = VaultSearcher(root, model, store)

            # Build probes from the manifest's needle keywords.
            probes: list[tuple[str, int, str, str]] = []
            for needle, doc_id in list(manifest.needles.items())[:8]:
                probes.append((needle, 5, f"Needle → {doc_id}", doc_id))

            table = Table(
                title="Quality Probes — Synthetic Corpus",
                show_header=True,
            )
            table.add_column("#", style="bold", justify="right")
            table.add_column("Label")
            table.add_column("Query", style="italic")
            table.add_column("Result", justify="center")

            passed = 0
            for i, (query, top_k, label, expected_id) in enumerate(
                probes,
                1,
            ):
                results = searcher.search_vault(query, top_k=top_k)
                ok = any(expected_id in r.id for r in results)
                if ok:
                    passed += 1
                status = "[green]PASS[/]" if ok else "[red]FAIL[/]"
                table.add_row(str(i), label, query, status)

            total = len(probes)
            precision = passed / total if total else 0
            _cli.console.print(table)
            _cli.console.print(
                f"\nPassed [bold]{passed}/{total}[/] probes "
                f"([cyan]{precision:.0%}[/] precision)",
            )

            threshold = 0.75
            if precision < threshold:
                _cli.console.print(
                    f"[bold red]FAILED[/] — precision {precision:.0%} "
                    f"below {threshold:.0%} threshold.",
                )
                raise typer.Exit(code=1)
            _cli.console.print("[bold green]PASSED[/]")
        finally:
            store.close()
