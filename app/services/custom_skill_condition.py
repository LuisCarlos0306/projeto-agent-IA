from __future__ import annotations

from typing import Any


CONDITION_OPERATORS = {
    "exit_code_nonzero",
    "exit_code_zero",
    "stdout_contains",
    "stdout_not_contains",
    "stdout_empty",
    "stdout_not_empty",
}


def condition_needs_action(
    operator: str,
    *,
    exit_code: int,
    stdout: str,
    expected: str = "",
) -> bool:
    """Retorna True somente quando a regra configurada exige atuação.

    A função não executa nada. Ela apenas interpreta o resultado de uma
    validação previamente executada em modo somente leitura.
    """
    op = str(operator or "exit_code_nonzero").strip().casefold()
    if op not in CONDITION_OPERATORS:
        raise ValueError("operador de condição inválido")

    text = str(stdout or "")
    compare = str(expected or "")
    if op == "exit_code_nonzero":
        return int(exit_code) != 0
    if op == "exit_code_zero":
        return int(exit_code) == 0
    if op == "stdout_contains":
        return compare in text
    if op == "stdout_not_contains":
        return compare not in text
    if op == "stdout_empty":
        return not text.strip()
    return bool(text.strip())


def build_condition_result(
    condition: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    operator = str(condition.get("operator") or "exit_code_nonzero")
    expected = str(condition.get("expected") or "")
    action_needed = condition_needs_action(
        operator,
        exit_code=int(validation.get("exit_code") or 0),
        stdout=str(validation.get("stdout") or ""),
        expected=expected,
    )
    return {
        "enabled": True,
        "operator": operator,
        "expected": expected,
        "action_needed": action_needed,
        "validation": validation,
        "post_validation": condition.get("post_validation"),
        "messages": dict(condition.get("messages") or {}),
    }
