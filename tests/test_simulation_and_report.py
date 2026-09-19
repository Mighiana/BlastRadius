"""What-if simulation (Priority 3) and PR report (Priority 5)."""

from blastradius import simulation
from blastradius.graph import analyze, build_graph, compare
from blastradius.parser import parse_directory
from blastradius.report import TITLE, build_report, responsible_change
from blastradius.security import remediation
from blastradius.security.decision import Decision, decide

from tests.conftest import SAFE_DIR, VULNERABLE_DIR


def _analyze(directory, label="x"):
    return analyze(build_graph(parse_directory(directory)), label)


# --- Priority 3: simulation ------------------------------------------------
def test_risky_simulation_is_applicable_to_the_safe_baseline():
    available = {s.id for s in simulation.available_simulations(SAFE_DIR)}
    assert "public_ssh" in available


def test_risky_simulation_is_not_applicable_to_the_vulnerable_config():
    available = {s.id for s in simulation.available_simulations(VULNERABLE_DIR)}
    assert "public_ssh" not in available, "CIDR is already public, nothing to widen"


def test_simulation_produces_the_same_result_as_the_committed_vulnerable_config(tmp_path):
    result = simulation.simulate(SAFE_DIR, tmp_path / "sim", simulation.SIMULATIONS["public_ssh"])
    assert result.applied and result.replacements == 1
    assert "0.0.0.0/0" in result.diff

    simulated = _analyze(result.directory, "simulated")
    committed = _analyze(VULNERABLE_DIR, "committed")
    assert simulated.path_keys == committed.path_keys
    assert simulated.score == committed.score
    assert simulated.risk_level is committed.risk_level


def test_simulated_change_blocks_the_merge(tmp_path):
    result = simulation.simulate(SAFE_DIR, tmp_path / "sim", simulation.SIMULATIONS["public_ssh"])
    diff = compare(_analyze(SAFE_DIR, "safe"), _analyze(result.directory, "sim"))
    assert decide(diff).decision is Decision.BLOCK
    assert len(diff.new_critical_paths) == 1


def test_broad_iam_simulation_raises_edge_risk_without_new_nodes(tmp_path):
    result = simulation.simulate(SAFE_DIR, tmp_path / "sim", simulation.SIMULATIONS["broad_iam"])
    assert result.applied

    after = _analyze(result.directory, "sim")
    edge = after.graph.edges["aws_iam_role.app", "aws_s3_bucket.customer_data"]["edge"]
    assert "s3:*" in edge.evidence
    # Still no internet entry point, so no attack path appears.
    assert after.critical_paths == []


def test_simulation_writes_a_complete_analysable_directory(tmp_path):
    result = simulation.simulate(SAFE_DIR, tmp_path / "sim", simulation.SIMULATIONS["public_ssh"])
    source_files = {p.name for p in SAFE_DIR.glob("*.tf")}
    assert {p.name for p in result.directory.glob("*.tf")} == source_files


def test_simulation_leaves_the_source_untouched(tmp_path):
    original = (SAFE_DIR / "main.tf").read_text(encoding="utf-8")
    simulation.simulate(SAFE_DIR, tmp_path / "sim", simulation.SIMULATIONS["public_ssh"])
    assert (SAFE_DIR / "main.tf").read_text(encoding="utf-8") == original


def test_inapplicable_simulation_is_a_noop(tmp_path):
    result = simulation.simulate(
        VULNERABLE_DIR, tmp_path / "sim", simulation.SIMULATIONS["public_ssh"]
    )
    assert not result.applied and result.diff == ""


# --- Priority 5: PR report -------------------------------------------------
def test_failed_report_contains_the_required_elements(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    report = build_report(diff, before_dir=SAFE_DIR, after_dir=VULNERABLE_DIR)

    assert TITLE in report
    assert "FAILED" in report and "PASSED" not in report
    assert "security regression" in report
    assert "+1 critical attack path" in report
    assert "+3 internet-reachable resources" in report
    assert "+1 sensitive resource reachable" in report
    assert "Internet -> Web SG -> Web Server -> App Role -> Customer Data" in report
    assert '10.0.0.0/24' in report and '0.0.0.0/0' in report
    assert "Restrict the public ingress CIDR before merging." in report


def test_passed_report_after_remediation(tmp_path, vulnerable_result):
    plan = remediation.generate_safer_config(VULNERABLE_DIR)
    fixed_dir = remediation.write_plan(plan, tmp_path / "fixed", VULNERABLE_DIR)
    fixed = _analyze(fixed_dir, "fixed")

    diff = compare(vulnerable_result, fixed)
    report = build_report(diff, before_dir=VULNERABLE_DIR, after_dir=fixed_dir)

    assert "PASSED" in report and "FAILED" not in report
    assert "removes an existing attack path" in report
    assert "-1 critical attack path" in report
    assert "Eliminated attack path:" in report
    assert "No action required." in report


def test_unchanged_report_passes_with_no_new_paths(safe_result):
    diff = compare(safe_result, _analyze(SAFE_DIR, "safe-copy"))
    report = build_report(diff, before_dir=SAFE_DIR, after_dir=SAFE_DIR)
    assert "PASSED" in report
    assert "No new critical attack paths detected." in report


def test_responsible_change_identifies_the_single_line():
    change = responsible_change(SAFE_DIR, VULNERABLE_DIR)
    assert "0.0.0.0/0" in change and "->" in change


def test_report_is_deterministic(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    first = build_report(diff, before_dir=SAFE_DIR, after_dir=VULNERABLE_DIR)
    second = build_report(diff, before_dir=SAFE_DIR, after_dir=VULNERABLE_DIR)
    assert first == second


def test_report_works_without_directories(safe_result, vulnerable_result):
    report = build_report(compare(safe_result, vulnerable_result))
    assert "FAILED" in report
    assert "Responsible Terraform change" not in report
