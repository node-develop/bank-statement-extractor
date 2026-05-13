"""Topology smoke tests for src/graph/builder.py — no real LLM calls.

These tests assert that the compiled graph has the expected node set and
conditional edges WITHOUT invoking any node.  They validate the wiring
contract (architecture.md) at import time.

Phase 3: topology now is
``merge_state → verifier → route_after_verifier → {reconcile|critic|await_review}``;
``critic → apply_critic_hint → [Send to extract_*] → merge_state``.
"""

from __future__ import annotations

from src.graph.builder import build_graph

# ---------------------------------------------------------------------------
# Expected node names (architecture.md graph topology, Phase 3)
# ---------------------------------------------------------------------------
_EXPECTED_NODES = {
    "ingest",
    "split_periods",
    "classify_layout",
    "extract_account",
    "extract_summary",
    "extract_transactions",
    "merge_state",
    "verifier",
    "reconcile",
    "critic",
    "apply_critic_hint",
    "await_review",
    "apply_human_corrections",
    "finalize",
    "__start__",
}


class TestBuildGraphTopology:
    """Assert the compiled graph matches the documented topology."""

    def test_build_graph_returns_without_checkpointer(self) -> None:
        graph = build_graph(checkpointer=None)
        assert graph is not None

    def test_expected_node_names_present(self) -> None:
        graph = build_graph(checkpointer=None)
        nodes = set(graph.get_graph().nodes.keys())
        missing = _EXPECTED_NODES - nodes
        assert not missing, f"Missing nodes: {missing}"

    def test_no_unexpected_nodes(self) -> None:
        graph = build_graph(checkpointer=None)
        nodes = set(graph.get_graph().nodes.keys())
        allowed_extras = {"__end__"}
        unexpected = nodes - _EXPECTED_NODES - allowed_extras
        assert not unexpected, f"Unexpected nodes: {unexpected}"

    def test_ingest_is_entry_point(self) -> None:
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("__start__", "ingest") in sources_to_targets

    def test_finalize_leads_to_end(self) -> None:
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("finalize", "__end__") in sources_to_targets

    def test_merge_state_has_four_upstream_extractors(self) -> None:
        """All four per-chunk nodes edge into merge_state. Critic re-extractor
        loop also lands here (via apply_critic_hint Send → extract_*)."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        upstream_of_merge = {e.source for e in edges if e.target == "merge_state"}
        expected_upstream = {
            "classify_layout",
            "extract_account",
            "extract_summary",
            "extract_transactions",
        }
        assert expected_upstream <= upstream_of_merge, (
            f"Expected {expected_upstream} ⊆ upstream_of_merge={upstream_of_merge}"
        )

    def test_verifier_downstream_of_merge_state(self) -> None:
        """Phase 3: merge_state → verifier (NOT directly to reconcile)."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("merge_state", "verifier") in sources_to_targets

    def test_reconcile_finalizes_directly(self) -> None:
        """Phase 3: reconcile → finalize (no should_run_critic in between)."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("reconcile", "finalize") in sources_to_targets

    def test_await_review_finalizes(self) -> None:
        """Phase 3: await_review → finalize (post-resume)."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("await_review", "finalize") in sources_to_targets
