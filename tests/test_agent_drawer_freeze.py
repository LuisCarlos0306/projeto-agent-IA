from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "app" / "ui" / "agent-correction-approval.js").read_text(encoding="utf-8")


def test_approval_button_observer_is_idempotent() -> None:
    assert "const existing = drawer.querySelector" in SCRIPT
    assert "existing.dataset.approveAgentCorrection === agentId" in SCRIPT
    assert "existing.parentElement === actions" in SCRIPT
    assert "return;" in SCRIPT
    assert "new MutationObserver(scheduleApprovalButtonRefresh)" in SCRIPT
    assert "queueMicrotask" in SCRIPT


def test_observer_no_longer_unconditionally_removes_button_before_checking_state() -> None:
    function_body = SCRIPT.split("function ensureApprovalButton()", 1)[1].split("function scheduleApprovalButtonRefresh()", 1)[0]
    guard_position = function_body.index("existing.dataset.approveAgentCorrection === agentId")
    remove_position = function_body.rindex("if (existing) existing.remove();")
    assert guard_position < remove_position
