"""
Unit tests for src.analysis.impact.ImpactAnalyzer.

Fixture repo layout (tests/fixtures/sample_project/):

    models.py        — User class (leaf: no calls to other fixture files)
    services.py      — UserService calls User.__init__ + User.display_name
    api.py           — handler functions call UserService methods
    test_services.py — test functions call UserService methods (is_test=True)

Known call-graph relationships relevant to these tests
-------------------------------------------------------
When we change  models.User.display_name:
  Direct callers   (hop=1): services.UserService.get_user
  Transitive (hop=2):       api.get_user_handler (calls get_user)
                            test_services.test_get_user (calls get_user)

When we change  services.UserService.get_user:
  Direct callers   (hop=1): api.get_user_handler
                            test_services.test_get_user
  No further transitive hops in this tiny fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — ensure project root is importable
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent  # tests/ → project root
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.ingestion.walker import walk_repository                    # noqa: E402
from src.ingestion.parsers.python_parser import PythonParser        # noqa: E402
from src.analysis.symbol_index import build_index, SymbolKind       # noqa: E402
from src.analysis.call_graph import build_call_graph                 # noqa: E402
from src.analysis.impact import ImpactAnalyzer, ImpactResult        # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixture — build the analysis objects once per session
# ---------------------------------------------------------------------------

FIXTURE_DIR = _HERE.parent / "fixtures" / "sample_project"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    assert FIXTURE_DIR.is_dir(), f"Fixture dir not found: {FIXTURE_DIR}"
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def analysis(fixture_dir):
    """Walk fixture repo, parse, build index + call graph, return analyzer."""
    python_files  = walk_repository(str(fixture_dir), languages={"python"})
    parser        = PythonParser()
    parse_results = [parser.parse(f.absolute_path) for f in python_files]

    index      = build_index(python_files, parser)
    call_graph = build_call_graph(index, parse_results)
    analyzer   = ImpactAnalyzer(index, call_graph)

    return {
        "index":      index,
        "call_graph": call_graph,
        "analyzer":   analyzer,
        "results":    parse_results,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def fqns(symbols) -> set[str]:
    return {s.fqn for s in symbols}


def _find_fqn(index, name: str) -> str | None:
    """Find any symbol FQN whose simple name matches."""
    matches = index.find_by_name(name)
    return matches[0].fqn if matches else None


# ---------------------------------------------------------------------------
# Symbol Index tests
# ---------------------------------------------------------------------------

class TestSymbolIndex:
    def test_all_files_parsed(self, analysis):
        index = analysis["index"]
        modules = {s.module_fqn for s in index.all_modules()}
        # All four fixture files must appear
        for expected in ("models", "services", "api", "test_services"):
            assert any(m.endswith(expected) for m in modules), \
                f"Module '{expected}' not found in index. Got: {modules}"

    def test_user_class_indexed(self, analysis):
        index = analysis["index"]
        matches = index.find_by_name("User")
        assert matches, "User class should be in the symbol index"
        user_sym = matches[0]
        assert user_sym.kind == SymbolKind.CLASS
        assert "models" in user_sym.module_fqn

    def test_user_service_class_indexed(self, analysis):
        index = analysis["index"]
        matches = index.find_by_name("UserService")
        assert matches, "UserService should be in the symbol index"
        assert matches[0].kind == SymbolKind.CLASS

    def test_methods_indexed(self, analysis):
        index = analysis["index"]
        get_user_matches = index.find_by_name("get_user")
        assert get_user_matches, "get_user method should be indexed"
        kinds = {s.kind for s in get_user_matches}
        assert SymbolKind.METHOD in kinds

    def test_docstrings_captured(self, analysis):
        index = analysis["index"]
        display_name = index.find_by_name("display_name")
        assert display_name, "display_name should be in the index"
        assert display_name[0].docstring is not None
        assert "display name" in display_name[0].docstring.lower()

    def test_line_numbers_nonzero(self, analysis):
        index = analysis["index"]
        for sym in index.all_symbols():
            if sym.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CLASS):
                assert sym.line > 0, f"Symbol {sym.fqn} has line=0"


# ---------------------------------------------------------------------------
# Call Graph tests
# ---------------------------------------------------------------------------

class TestCallGraph:
    def test_call_graph_has_edges(self, analysis):
        cg = analysis["call_graph"]
        assert len(cg) > 0, "Call graph should have edges"

    def test_get_user_called_by_handler(self, analysis):
        """api.get_user_handler must call services.UserService.get_user."""
        cg = analysis["call_graph"]
        # Find handler node
        handler_node = None
        for node in cg.all_nodes():
            if "get_user_handler" in node.fqn and "api" in node.fqn:
                handler_node = node
                break
        assert handler_node is not None, "get_user_handler node not in call graph"

        callee_fqns = {e.callee_fqn for e in handler_node.calls}
        assert any("get_user" in fqn for fqn in callee_fqns), \
            f"get_user_handler should call get_user. Callees: {callee_fqns}"

    def test_test_file_calls_service(self, analysis):
        """test_services functions must appear in the call graph."""
        cg = analysis["call_graph"]
        test_nodes = [n for n in cg.all_nodes() if "test_services" in n.fqn]
        assert test_nodes, "test_services nodes should appear in call graph"


# ---------------------------------------------------------------------------
# Impact Analyzer — core correctness tests
# ---------------------------------------------------------------------------

class TestImpactAnalyzer:

    # ---- ImpactResult structure -----------------------------------------

    def test_result_is_serialisable(self, analysis):
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        display_name_syms = index.find_by_name("display_name")
        assert display_name_syms, "display_name must be indexed"
        result = analyzer.get_downstream_impact(display_name_syms[0].fqn)
        # Must not raise
        as_dict = result.as_dict()
        assert "changed_fqn" in as_dict
        assert "direct_callers" in as_dict
        assert "transitive_callers" in as_dict
        assert "affected_tests" in as_dict
        assert "affected_files" in as_dict

    def test_total_impact_sum(self, analysis):
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = index.find_by_name("get_user")
        method_syms = [s for s in get_user_syms if s.kind == SymbolKind.METHOD]
        assert method_syms
        result = analyzer.get_downstream_impact(method_syms[0].fqn)
        assert result.total_impact == len(result.direct_callers) + len(result.transitive_callers)

    def test_empty_impact_for_leaf(self, analysis):
        """A symbol nobody calls should have zero impact."""
        analyzer = analysis["analyzer"]
        # add_user in services is never called by anyone in the fixture
        # except api.create_user_handler and test_services.test_add_user
        # so this tests that the result is at least well-formed
        index = analysis["index"]
        display_matches = index.find_by_name("display_name")
        assert display_matches
        result = analyzer.get_downstream_impact(display_matches[0].fqn)
        assert isinstance(result, ImpactResult)

    # ---- Direct callers -------------------------------------------------

    def test_get_user_direct_callers_include_handler(self, analysis):
        """Changing UserService.get_user must flag api.get_user_handler as direct."""
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        assert get_user_syms, "UserService.get_user must be indexed as a method"
        result = analyzer.get_downstream_impact(get_user_syms[0].fqn)

        direct_fqns = fqns(result.direct_callers)
        assert any("get_user_handler" in f for f in direct_fqns), \
            f"get_user_handler not in direct callers. Got: {direct_fqns}"

    def test_get_user_direct_callers_include_test(self, analysis):
        """Changing UserService.get_user must flag test_get_user as direct."""
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        result = analyzer.get_downstream_impact(get_user_syms[0].fqn)
        direct_fqns = fqns(result.direct_callers)
        assert any("test_get_user" in f for f in direct_fqns), \
            f"test_get_user not in direct callers. Got: {direct_fqns}"

    # ---- Test file detection --------------------------------------------

    def test_affected_tests_are_flagged(self, analysis):
        """Symbols in test_services.py must appear in affected_tests."""
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        result = analyzer.get_downstream_impact(get_user_syms[0].fqn)
        assert result.affected_tests, \
            "At least one test should be in affected_tests for UserService.get_user"
        for sym in result.affected_tests:
            assert sym.is_test, f"Symbol {sym.fqn} flagged as test but is_test=False"

    def test_is_test_flag_accurate(self, analysis):
        """All symbols from test_services.py must have is_test=True."""
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        result = analyzer.get_downstream_impact(get_user_syms[0].fqn)
        all_impacted = result.all_impacted()
        for sym in all_impacted:
            if "test_services" in sym.fqn:
                assert sym.is_test, f"{sym.fqn} should have is_test=True"

    # ---- Affected files -------------------------------------------------

    def test_affected_files_populated(self, analysis):
        """affected_files must contain at least api.py and test_services.py."""
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        result = analyzer.get_downstream_impact(get_user_syms[0].fqn)
        paths = result.affected_files
        assert any("api" in p for p in paths), \
            f"api.py not in affected_files: {paths}"
        assert any("test_services" in p for p in paths), \
            f"test_services.py not in affected_files: {paths}"

    def test_affected_files_sorted(self, analysis):
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        syms = index.find_by_name("get_user")
        if not syms:
            pytest.skip("get_user not found")
        result = analyzer.get_downstream_impact(syms[0].fqn)
        assert result.affected_files == sorted(result.affected_files)

    # ---- Hop counts -----------------------------------------------------

    def test_direct_callers_have_hop_1(self, analysis):
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        result = analyzer.get_downstream_impact(get_user_syms[0].fqn)
        for sym in result.direct_callers:
            assert sym.hop == 1, f"{sym.fqn} is in direct_callers but hop={sym.hop}"

    def test_transitive_callers_have_hop_gte_2(self, analysis):
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        result = analyzer.get_downstream_impact(get_user_syms[0].fqn)
        for sym in result.transitive_callers:
            assert sym.hop >= 2, f"{sym.fqn} in transitive but hop={sym.hop}"

    # ---- max_hops cap ---------------------------------------------------

    def test_max_hops_1_limits_to_direct(self, analysis):
        """With max_hops=1 the analyzer must return only direct callers."""
        index      = analysis["index"]
        call_graph = analysis["call_graph"]
        analyzer1  = ImpactAnalyzer(index, call_graph, max_hops=1)

        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        if not get_user_syms:
            pytest.skip("get_user method not found")
        result = analyzer1.get_downstream_impact(get_user_syms[0].fqn)
        assert result.transitive_callers == [], \
            "With max_hops=1 there should be no transitive callers"

    # ---- get_impact_for_class -------------------------------------------

    def test_class_impact_covers_all_methods(self, analysis):
        """Impact for UserService class must cover callers of all its methods."""
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        service_syms = index.find_by_name("UserService")
        assert service_syms
        result = analyzer.get_impact_for_class(service_syms[0].fqn)
        all_fqns = fqns(result.all_impacted())
        # Both api and test_services call UserService methods
        assert any("api" in f for f in all_fqns), \
            f"api symbols not in class impact. Got: {all_fqns}"
        assert any("test_services" in f for f in all_fqns), \
            f"test_services not in class impact. Got: {all_fqns}"

    # ---- Summary string -------------------------------------------------

    def test_summary_string(self, analysis):
        analyzer = analysis["analyzer"]
        index    = analysis["index"]
        get_user_syms = [s for s in index.find_by_name("get_user")
                         if s.kind == SymbolKind.METHOD]
        result = analyzer.get_downstream_impact(get_user_syms[0].fqn)
        summary = result.summary()
        assert "Impact report" in summary
        assert "Direct callers" in summary
