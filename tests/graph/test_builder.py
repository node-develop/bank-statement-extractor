"""Topology smoke tests for src/graph/builder.py — no real LLM calls.

These tests assert that the compiled graph has the expected node set and
conditional edges WITHOUT invoking any node.  They validate the wiring
contract (architecture.md) at import time.
"""

from __future__ import annotations

from src.graph.builder import build_graph

# ---------------------------------------------------------------------------
# Expected node names (architecture.md graph topology)
# ---------------------------------------------------------------------------
_EXPECTED_NODES = {
    "ingest",
    "split_periods",
    "classify_layout",
    "extract_account",
    "extract_summary",
    "extract_transactions",
    "merge_state",
    "reconcile",
    "critic",
    "finalize",
    "__start__",
}


class TestBuildGraphTopology:
    """Assert the compiled graph matches the documented topology."""

    def test_build_graph_returns_without_checkpointer(self) -> None:
        """build_graph(checkpointer=None) compiles cleanly."""
        graph = build_graph(checkpointer=None)
        assert graph is not None

    def test_expected_node_names_present(self) -> None:
        """All documented nodes are present in the compiled graph."""
        graph = build_graph(checkpointer=None)
        nodes = set(graph.get_graph().nodes.keys())
        missing = _EXPECTED_NODES - nodes
        assert not missing, f"Missing nodes: {missing}"

    def test_no_unexpected_nodes(self) -> None:
        """No undocumented nodes snuck into the graph (plus LangGraph internals)."""
        graph = build_graph(checkpointer=None)
        nodes = set(graph.get_graph().nodes.keys())
        # Allow the LangGraph END sentinel if it appears as a node.
        allowed_extras = {"__end__"}
        unexpected = nodes - _EXPECTED_NODES - allowed_extras
        assert not unexpected, f"Unexpected nodes: {unexpected}"

    def test_ingest_is_entry_point(self) -> None:
        """START → ingest is the first edge."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        # Each edge is a (source, target) namedtuple or similar.
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("__start__", "ingest") in sources_to_targets

    def test_finalize_leads_to_end(self) -> None:
        """finalize → END is the terminal edge."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("finalize", "__end__") in sources_to_targets

    def test_merge_state_has_four_upstream_extractors(self) -> None:
        """All four per-chunk nodes edge into merge_state."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        upstream_of_merge = {e.source for e in edges if e.target == "merge_state"}
        expected_upstream = {
            "classify_layout",
            "extract_account",
            "extract_summary",
            "extract_transactions",
            # critic loops back through merge_state
            "critic",
        }
        assert expected_upstream <= upstream_of_merge, (
            f"Expected {expected_upstream} ⊆ upstream_of_merge={upstream_of_merge}"
        )

    def test_reconcile_downstream_of_merge_state(self) -> None:
        """merge_state → reconcile edge is present."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("merge_state", "reconcile") in sources_to_targets

    def test_critic_loops_back_to_merge_state(self) -> None:
        """critic → merge_state edge creates the retry loop."""
        graph = build_graph(checkpointer=None)
        edges = graph.get_graph().edges
        sources_to_targets = {(e.source, e.target) for e in edges}
        assert ("critic", "merge_state") in sources_to_targets
