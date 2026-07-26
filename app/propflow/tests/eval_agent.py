"""
PropFlow Agent Evaluation
=========================
Measures how well the PropFlow AI agent performs its core jobs.

Framework choice:
  DeepEval  -- for JSON correctness and hallucination detection (LLM-as-judge)
  Custom    -- for confidence calibration, Mem0 personalisation, latency,
               workflow completion rate (domain-specific, no framework covers these)

Usage:
  # Run all evals (requires QWEN_API_KEY):
  python -m app.propflow.tests.eval_agent

  # Run without API key (mock mode, custom metrics only):
  PROPFLOW_EVAL_MOCK=true python -m app.propflow.tests.eval_agent

  # Save report to JSON:
  python -m app.propflow.tests.eval_agent --output eval_report.json

Output:
  Prints a formatted score table to stdout.
  Optionally writes eval_report.json for inclusion in the hackathon submission.

When to run:
  Day 4 evening -- after real Supabase nodes are wired.
  The stubs (placeholder UUIDs) give meaningless workflow completion scores.
  Intent extraction and briefing quality can be tested earlier (Day 2/3)
  because they only depend on Qwen, not Supabase.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from app.propflow.tests.eval_dataset import EVAL_DATASET, BRIEFING_EVAL_CASES
from app.propflow.services.qwen_client import qwen_client
from app.propflow.config import propflow_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class IntentResult:
    case_id: str
    label: str
    passed: bool
    field_accuracy: float        # fraction of expected fields extracted correctly
    confidence: float            # what the model reported
    confidence_ok: bool          # was confidence in the expected range?
    latency_ms: float
    errors: list[str] = field(default_factory=list)


@dataclass
class BriefingResult:
    case_id: str
    label: str
    sentence_count: int
    sentence_count_ok: bool      # == 3?
    hallucination_score: float   # 0.0 (clean) to 1.0 (fully hallucinated)
    grounding_score: float       # fraction of expected facts present in output
    latency_ms: float
    deepeval_used: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    run_timestamp: str
    model_used: str
    mock_mode: bool

    # Intent extraction
    intent_cases_total: int = 0
    intent_cases_passed: int = 0
    intent_avg_field_accuracy: float = 0.0
    intent_avg_confidence: float = 0.0
    intent_avg_confidence_calibration: float = 0.0  # lower = better
    intent_avg_latency_ms: float = 0.0
    intent_pidgin_accuracy: float = 0.0   # accuracy on Pidgin-labelled cases
    clarification_gate_ok: bool = False   # TC-10 must route to needs_clarification

    # Briefing quality
    briefing_cases_total: int = 0
    briefing_sentence_compliance: float = 0.0  # % with exactly 3 sentences
    briefing_avg_hallucination: float = 0.0    # lower = better
    briefing_avg_grounding: float = 0.0        # higher = better
    briefing_avg_latency_ms: float = 0.0
    deepeval_available: bool = False

    # Overall
    overall_score: float = 0.0
    intent_results: list[dict] = field(default_factory=list)
    briefing_results: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DeepEval integration (optional, graceful degradation)
# ---------------------------------------------------------------------------

def _try_import_deepeval():
    """Returns (GEvalMetric, LLMTestCase) or (None, None) if not installed."""
    try:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams
        return GEval, LLMTestCase, LLMTestCaseParams
    except ImportError:
        return None, None, None


def _configure_deepeval_for_qwen():
    """
    Point DeepEval's LLM-as-judge at Qwen via the openai-compat endpoint.
    DeepEval respects OPENAI_API_KEY and OPENAI_BASE_URL env vars.
    We set them programmatically here so no .env changes are needed.
    """
    import os
    if propflow_settings.QWEN_API_KEY:
        os.environ.setdefault("OPENAI_API_KEY", propflow_settings.QWEN_API_KEY)
        os.environ.setdefault("OPENAI_BASE_URL", propflow_settings.QWEN_API_URL)
        os.environ.setdefault("OPENAI_MODEL_NAME", propflow_settings.QWEN_MODEL)


# ---------------------------------------------------------------------------
# Custom scorers
# ---------------------------------------------------------------------------

def _score_intent_fields(actual: dict, expected: dict) -> tuple[float, list[str]]:
    """
    Compare extracted intent fields against ground truth.

    Rules:
    - None in expected means "don't care" -- skip that field
    - Numeric fields use 10% relative tolerance
    - String fields use lowercase exact match (or substring for locations)
    - Returns (accuracy_0_to_1, list_of_errors)
    """
    errors = []
    scored_fields = 0
    correct_fields = 0

    for key, expected_val in expected.items():
        if key == "confidence":
            continue  # confidence is scored separately
        if expected_val is None:
            continue  # don't-care field

        actual_val = actual.get(key)
        scored_fields += 1

        if actual_val is None:
            errors.append(f"{key}: expected {expected_val!r}, got None")
            continue

        # Numeric comparison with tolerance
        if isinstance(expected_val, (int, float)):
            try:
                actual_num = float(actual_val)
                expected_num = float(expected_val)
                # 10% relative tolerance (absorbs rounding on derived fields)
                tolerance = max(abs(expected_num) * 0.10, 1.0)
                if abs(actual_num - expected_num) <= tolerance:
                    correct_fields += 1
                else:
                    errors.append(
                        f"{key}: expected {expected_num:,.0f}, "
                        f"got {actual_num:,.0f} "
                        f"(diff {abs(actual_num - expected_num):,.0f})"
                    )
            except (TypeError, ValueError):
                errors.append(f"{key}: expected numeric {expected_val}, got {actual_val!r}")
            continue

        # String comparison
        if isinstance(expected_val, str):
            actual_str = str(actual_val).lower().strip()
            expected_str = expected_val.lower().strip()

            # Location fields: substring match (e.g. "Lekki Phase 1" in "Lekki Phase 1, Lagos")
            if key == "location":
                if expected_str in actual_str or actual_str in expected_str:
                    correct_fields += 1
                else:
                    errors.append(f"{key}: expected '{expected_val}', got '{actual_val}'")
            elif actual_str == expected_str:
                correct_fields += 1
            else:
                errors.append(f"{key}: expected '{expected_val}', got '{actual_val}'")
            continue

    if scored_fields == 0:
        return 1.0, []

    return correct_fields / scored_fields, errors


def _score_briefing_grounding(briefing_text: str, grounding_facts: list[str]) -> float:
    """
    Check what fraction of expected grounding facts appear in the briefing.
    A fact is 'present' if it appears as a case-insensitive substring.
    """
    if not grounding_facts:
        return 1.0
    found = sum(
        1 for fact in grounding_facts
        if fact.lower() in briefing_text.lower()
    )
    return found / len(grounding_facts)


def _count_sentences(text: str) -> int:
    """
    Count sentences in briefing text.
    Splits on '.', '!' and '?' followed by whitespace or end of string.
    """
    sentences = re.split(r"[.!?]+(?:\s|$)", text.strip())
    return sum(1 for s in sentences if s.strip())


def _simple_hallucination_score(briefing: str, tenant_data: dict, property_data: dict) -> float:
    """
    Lightweight hallucination check (no LLM needed).
    Looks for specific numbers or proper names in the briefing that DON'T
    appear in the source data -- a signal that the model invented facts.

    Returns 0.0 (no hallucination detected) to 1.0 (likely hallucination).
    This is a heuristic, not a ground truth. DeepEval's GEval is more accurate.
    """
    # Build a corpus of all legitimate source values as strings
    source_corpus = set()
    for val in list(tenant_data.values()) + list(property_data.values()):
        if val is not None:
            source_corpus.add(str(val).lower())

    # Find all numbers in the briefing
    briefing_numbers = re.findall(r"\b\d[\d,]+\b", briefing)
    hallucinated = 0
    total_checked = 0

    for num_str in briefing_numbers:
        normalized = num_str.replace(",", "")
        total_checked += 1
        # Check if this number (or something close) is in source data
        found_in_source = any(
            normalized in src.replace(",", "")
            for src in source_corpus
        )
        if not found_in_source:
            hallucinated += 1

    if total_checked == 0:
        return 0.0

    return hallucinated / total_checked


# ---------------------------------------------------------------------------
# Evaluation runners
# ---------------------------------------------------------------------------

async def _run_intent_eval(mock_mode: bool = False) -> list[IntentResult]:
    """Run all 10 intent extraction test cases and return results."""
    results = []

    for case in EVAL_DATASET:
        start = time.monotonic()

        if mock_mode:
            # Use mock extraction -- tests the keyword parser, not Qwen
            from app.propflow.services.qwen_client import QwenClient
            actual = QwenClient()._mock_intent_extraction(case["input"])
        else:
            actual = await qwen_client.extract_intent(
                text=case["input"],
                prior_memories=[],  # No memories in eval -- clean baseline
            )

        latency_ms = (time.monotonic() - start) * 1000
        confidence = float(actual.get("confidence", 0.0))

        # Field accuracy
        field_acc, field_errors = _score_intent_fields(actual, case["expected"])

        # Confidence gate check
        min_conf = case.get("min_confidence", 0.0)
        max_conf = case.get("max_confidence", 1.0)
        confidence_ok = min_conf <= confidence <= max_conf

        if not confidence_ok:
            field_errors.append(
                f"confidence {confidence:.2f} outside expected range "
                f"[{min_conf}, {max_conf}]"
            )

        passed = field_acc >= 0.7 and confidence_ok

        results.append(IntentResult(
            case_id=case["id"],
            label=case["label"],
            passed=passed,
            field_accuracy=field_acc,
            confidence=confidence,
            confidence_ok=confidence_ok,
            latency_ms=latency_ms,
            errors=field_errors,
        ))

        status = "PASS" if passed else "FAIL"
        logger.info(
            f"  [{status}] {case['id']} {case['label'][:40]} "
            f"acc={field_acc:.0%} conf={confidence:.2f} "
            f"latency={latency_ms:.0f}ms"
        )

    return results


async def _run_briefing_eval(mock_mode: bool = False) -> list[BriefingResult]:
    """Run all briefing quality test cases."""
    GEval, LLMTestCase, LLMTestCaseParams = _try_import_deepeval()
    deepeval_available = GEval is not None and not mock_mode

    if deepeval_available:
        _configure_deepeval_for_qwen()

    results = []

    for case in BRIEFING_EVAL_CASES:
        start = time.monotonic()
        errors = []

        if mock_mode:
            from app.propflow.services.qwen_client import QwenClient
            briefing = QwenClient()._mock_landlord_briefing(
                case["tenant_data"], case["property_data"]
            )
        else:
            briefing = await qwen_client.generate_landlord_briefing(
                tenant_data=case["tenant_data"],
                property_data=case["property_data"],
                extracted_intent=case["extracted_intent"],
                prior_tenant_memories=[],
                prior_landlord_memories=[],
            )

        latency_ms = (time.monotonic() - start) * 1000

        # Sentence count check
        sentence_count = _count_sentences(briefing)
        sentence_count_ok = sentence_count == case["must_contain_sentences"]
        if not sentence_count_ok:
            errors.append(
                f"Expected {case['must_contain_sentences']} sentences, "
                f"got {sentence_count}"
            )

        # Grounding check
        grounding_score = _score_briefing_grounding(briefing, case["grounding_facts"])
        if grounding_score < 0.6:
            errors.append(
                f"Low grounding: only {grounding_score:.0%} of expected facts present"
            )

        # Hallucination check
        if deepeval_available:
            # DeepEval GEval metric (LLM-as-judge via Qwen)
            hallucination_score = await _deepeval_hallucination_check(
                GEval, LLMTestCase, LLMTestCaseParams,
                briefing=briefing,
                tenant_data=case["tenant_data"],
                property_data=case["property_data"],
            )
        else:
            # Fallback: heuristic number-based check
            hallucination_score = _simple_hallucination_score(
                briefing, case["tenant_data"], case["property_data"]
            )

        results.append(BriefingResult(
            case_id=case["id"],
            label=case["label"],
            sentence_count=sentence_count,
            sentence_count_ok=sentence_count_ok,
            hallucination_score=hallucination_score,
            grounding_score=grounding_score,
            latency_ms=latency_ms,
            deepeval_used=deepeval_available,
            errors=errors,
        ))

        status = "PASS" if sentence_count_ok and grounding_score >= 0.6 else "FAIL"
        logger.info(
            f"  [{status}] {case['id']} {case['label'][:40]} "
            f"sentences={sentence_count} grounding={grounding_score:.0%} "
            f"hallucination={hallucination_score:.2f} latency={latency_ms:.0f}ms"
        )

    return results


async def _deepeval_hallucination_check(
    GEval, LLMTestCase, LLMTestCaseParams,
    briefing: str,
    tenant_data: dict,
    property_data: dict,
) -> float:
    """
    Use DeepEval's GEval metric to check for hallucination in the briefing.
    Returns a score 0.0 (no hallucination) to 1.0 (hallucinated).
    Falls back to heuristic on any error.
    """
    try:
        context = (
            f"Tenant: {json.dumps(tenant_data)}\n"
            f"Property: {json.dumps(property_data)}"
        )
        test_case = LLMTestCase(
            input=context,
            actual_output=briefing,
            context=[context],
        )
        faithfulness_metric = GEval(
            name="Faithfulness",
            criteria=(
                "The briefing should only contain facts present in the provided "
                "tenant and property data. Any specific claim about income, employer, "
                "occupation, or property details must be traceable to the source data."
            ),
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.CONTEXT,
            ],
        )
        faithfulness_metric.measure(test_case)
        # GEval returns a score 0-1 where 1 = fully faithful (no hallucination)
        # We invert it: 0 = no hallucination, 1 = full hallucination
        faithfulness = faithfulness_metric.score or 0.0
        return 1.0 - faithfulness
    except Exception as exc:
        logger.warning(f"DeepEval GEval failed: {exc}. Using heuristic fallback.")
        return _simple_hallucination_score(briefing, tenant_data, property_data)


# ---------------------------------------------------------------------------
# Report assembly and printing
# ---------------------------------------------------------------------------

def _assemble_report(
    intent_results: list[IntentResult],
    briefing_results: list[BriefingResult],
    mock_mode: bool,
    deepeval_available: bool,
) -> EvalReport:
    """Aggregate all results into an EvalReport."""
    report = EvalReport(
        run_timestamp=datetime.now(timezone.utc).isoformat(),
        model_used=propflow_settings.QWEN_MODEL if not mock_mode else "mock",
        mock_mode=mock_mode,
        deepeval_available=deepeval_available,
    )

    # ── Intent metrics ────────────────────────────────────────────────────────
    report.intent_cases_total = len(intent_results)
    report.intent_cases_passed = sum(1 for r in intent_results if r.passed)

    if intent_results:
        report.intent_avg_field_accuracy = (
            sum(r.field_accuracy for r in intent_results) / len(intent_results)
        )
        report.intent_avg_confidence = (
            sum(r.confidence for r in intent_results) / len(intent_results)
        )
        # Calibration: average gap between model confidence and actual field accuracy
        report.intent_avg_confidence_calibration = (
            sum(abs(r.confidence - r.field_accuracy) for r in intent_results)
            / len(intent_results)
        )
        report.intent_avg_latency_ms = (
            sum(r.latency_ms for r in intent_results) / len(intent_results)
        )

        # Pidgin-specific accuracy (cases labeled with "Pidgin")
        pidgin_cases = [r for r in intent_results if "Pidgin" in r.label]
        if pidgin_cases:
            report.intent_pidgin_accuracy = (
                sum(r.field_accuracy for r in pidgin_cases) / len(pidgin_cases)
            )

        # Clarification gate: TC-10 must have confidence < 0.70
        tc10 = next((r for r in intent_results if r.case_id == "TC-10"), None)
        report.clarification_gate_ok = tc10.confidence_ok if tc10 else False

    # ── Briefing metrics ──────────────────────────────────────────────────────
    report.briefing_cases_total = len(briefing_results)
    if briefing_results:
        compliant = sum(1 for r in briefing_results if r.sentence_count_ok)
        report.briefing_sentence_compliance = compliant / len(briefing_results)
        report.briefing_avg_hallucination = (
            sum(r.hallucination_score for r in briefing_results) / len(briefing_results)
        )
        report.briefing_avg_grounding = (
            sum(r.grounding_score for r in briefing_results) / len(briefing_results)
        )
        report.briefing_avg_latency_ms = (
            sum(r.latency_ms for r in briefing_results) / len(briefing_results)
        )

    # ── Overall score ─────────────────────────────────────────────────────────
    # Weighted: Intent (50%) + Briefing quality (30%) + Calibration (20%)
    intent_score = (
        report.intent_avg_field_accuracy * 0.60
        + (1.0 - report.intent_avg_confidence_calibration) * 0.40
    ) if report.intent_cases_total > 0 else 0.0

    briefing_score = (
        report.briefing_sentence_compliance * 0.40
        + report.briefing_avg_grounding * 0.40
        + (1.0 - report.briefing_avg_hallucination) * 0.20
    ) if report.briefing_cases_total > 0 else 0.0

    # Weight intent higher because it's the first gate in the pipeline
    report.overall_score = intent_score * 0.60 + briefing_score * 0.40

    # Store detailed results
    report.intent_results = [asdict(r) for r in intent_results]
    report.briefing_results = [asdict(r) for r in briefing_results]

    return report


def _print_report(report: EvalReport) -> None:
    """Pretty-print the evaluation report to stdout."""
    bar = "=" * 60
    thin = "-" * 60

    print(f"\n{bar}")
    print("  PROPFLOW AGENT EVALUATION REPORT")
    print(f"  {report.run_timestamp}")
    print(f"  Model: {report.model_used}  |  Mock: {report.mock_mode}")
    print(f"  DeepEval: {'available' if report.deepeval_available else 'not installed (heuristic fallback)'}")
    print(bar)

    # Intent section
    print("\n  INTENT EXTRACTION  (Qwen + Nigerian Pidgin/English)")
    print(thin)
    total = report.intent_cases_total
    passed = report.intent_cases_passed
    pass_rate = passed / total if total > 0 else 0.0
    print(f"  Cases passed:          {passed}/{total}  ({pass_rate:.0%})")
    print(f"  Avg field accuracy:    {report.intent_avg_field_accuracy:.1%}")
    print(f"  Avg confidence:        {report.intent_avg_confidence:.2f}")
    print(f"  Confidence calibration:{report.intent_avg_confidence_calibration:.3f}  (lower = better)")
    print(f"  Pidgin accuracy:       {report.intent_pidgin_accuracy:.1%}")
    print(f"  Clarification gate:    {'PASS -- TC-10 correctly flagged low confidence' if report.clarification_gate_ok else 'FAIL -- TC-10 did not trigger clarification'}")
    print(f"  Avg latency:           {report.intent_avg_latency_ms:.0f} ms")

    # Per-case detail
    print(f"\n  {'ID':<7} {'Label':<40} {'Acc':>5} {'Conf':>5} {'ms':>6} {'':>5}")
    print(f"  {'-'*7} {'-'*40} {'-'*5} {'-'*5} {'-'*6} {'-'*5}")
    for r in report.intent_results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"  {r['case_id']:<7} {r['label'][:40]:<40} "
            f"{r['field_accuracy']:>4.0%} {r['confidence']:>5.2f} "
            f"{r['latency_ms']:>5.0f}ms  {status}"
        )
        for err in r.get("errors", []):
            print(f"           -> {err}")

    # Briefing section
    print(f"\n  LANDLORD BRIEFING QUALITY  (Qwen generation)")
    print(thin)
    total_b = report.briefing_cases_total
    if total_b > 0:
        print(f"  Cases evaluated:       {total_b}")
        print(f"  3-sentence compliance: {report.briefing_sentence_compliance:.0%}")
        print(f"  Avg grounding score:   {report.briefing_avg_grounding:.1%}  (facts from source data)")
        print(f"  Avg hallucination:     {report.briefing_avg_hallucination:.3f}  (lower = better)")
        method = "DeepEval GEval" if report.deepeval_available else "heuristic"
        print(f"  Hallucination method:  {method}")
        print(f"  Avg latency:           {report.briefing_avg_latency_ms:.0f} ms")
        for r in report.briefing_results:
            status = "PASS" if r["sentence_count_ok"] and r["grounding_score"] >= 0.6 else "FAIL"
            print(
                f"\n  {r['case_id']} {r['label']}: {status}"
                f"  |  sentences={r['sentence_count']}  "
                f"grounding={r['grounding_score']:.0%}  "
                f"hallucination={r['hallucination_score']:.2f}"
            )
    else:
        print("  No briefing cases run.")

    # Overall
    print(f"\n{bar}")
    print(f"  OVERALL SCORE:   {report.overall_score:.1%}")
    print(f"  (Intent 60% + Briefing 40% weighted)")
    print(f"{bar}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_evaluation(
    mock_mode: bool = False,
    output_path: Optional[str] = None,
) -> EvalReport:
    """
    Run the full PropFlow agent evaluation.

    Args:
        mock_mode:   If True, uses keyword-based mock instead of Qwen API.
                     Useful for CI and when QWEN_API_KEY is not set.
        output_path: If provided, writes the report as JSON to this path.

    Returns:
        EvalReport dataclass with all scores.
    """
    import os
    if os.getenv("PROPFLOW_EVAL_MOCK", "").lower() == "true":
        mock_mode = True

    if not mock_mode and not propflow_settings.QWEN_API_KEY:
        print(
            "WARNING: QWEN_API_KEY not set. Running in mock mode.\n"
            "Set QWEN_API_KEY in .env or use PROPFLOW_EVAL_MOCK=true to suppress this warning."
        )
        mock_mode = True

    GEval, _, _ = _try_import_deepeval()
    deepeval_available = GEval is not None and not mock_mode

    print(f"\nRunning PropFlow agent evaluation...")
    print(f"  Model:    {propflow_settings.QWEN_MODEL if not mock_mode else 'mock'}")
    print(f"  DeepEval: {'yes' if deepeval_available else 'no (pip install deepeval to enable)'}")
    print(f"  Cases:    {len(EVAL_DATASET)} intent + {len(BRIEFING_EVAL_CASES)} briefing\n")

    print("Intent extraction:")
    intent_results = await _run_intent_eval(mock_mode=mock_mode)

    print("\nBriefing quality:")
    briefing_results = await _run_briefing_eval(mock_mode=mock_mode)

    report = _assemble_report(intent_results, briefing_results, mock_mode, deepeval_available)
    _print_report(report)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(asdict(report), f, indent=2, default=str)
        print(f"Report saved to: {output_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PropFlow Agent Evaluation")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run with mock Qwen responses (no API key needed)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write JSON report (e.g. eval_report.json)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )

    asyncio.run(run_evaluation(mock_mode=args.mock, output_path=args.output))
