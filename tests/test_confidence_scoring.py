from app.services.confidence_scoring import evidence_confidence, validated_confidence


def test_successful_evidence_produces_nonzero_confidence():
    evidence = [{"status": "executed", "exit_code": 0}]
    assert evidence_confidence(evidence) > 0


def test_inconclusive_confidence_stays_in_low_band():
    score, basis = validated_confidence(
        status="inconclusive",
        analysis={"status": "inconclusive", "confidence": 0},
        evidence=[{"status": "executed", "exit_code": 0}],
        assessments=[],
    )
    assert 1 <= score <= 39
    assert basis["evidence_successful"] == 1


def test_conclusive_result_uses_evidence_when_ai_returns_zero():
    score, basis = validated_confidence(
        status="healthy",
        analysis={"status": "healthy", "confidence": 0},
        evidence=[
            {"status": "executed", "exit_code": 0},
            {"status": "executed", "exit_code": 0},
            {"status": "executed", "exit_code": 0},
            {"status": "executed", "exit_code": 0},
        ],
        assessments=[],
    )
    assert score >= 70
    assert basis["evidence_total"] == 4


def test_insufficient_critic_caps_confidence_below_medium():
    score, basis = validated_confidence(
        status="healthy",
        analysis={
            "status": "healthy",
            "confidence": 90,
            "critic": {
                "verdict": "insufficient",
                "confidence": 80,
                "evidence_coverage": 50,
            },
        },
        evidence=[{"status": "executed", "exit_code": 0}] * 5,
        assessments=[],
    )
    assert score <= 39
    assert basis["critic_verdict"] == "insufficient"


def test_accepted_critic_limits_to_coverage():
    score, _basis = validated_confidence(
        status="healthy",
        analysis={
            "status": "healthy",
            "confidence": 95,
            "critic": {
                "verdict": "accept",
                "confidence": 88,
                "evidence_coverage": 82,
            },
        },
        evidence=[{"status": "executed", "exit_code": 0}] * 5,
        assessments=[],
    )
    assert score == 82
