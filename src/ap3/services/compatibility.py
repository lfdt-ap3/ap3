"""Compatibility checking between AP3 commitments and agent parameters.

Design goals:
- **Explainable**: return the reason for refusal, not just a boolean.
- **Realistic**: select the best pair among commitments (even if today most
  deployments only publish one).
- **Protocol-aware (optional)**: allow the caller to tighten rules for a
  particular operation type (e.g. PSI).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from ap3.types import (
    AP3ExtensionParameters,
    CommitmentMetadata,
    DataFreshness,
    DataFormat,
    DataStructure,
)


class CommitmentCompatibilityChecker:
    """Explainable compatibility checks for AP3 peers."""

    # Minimum score required to proceed with an AP3 protocol run.
    #
    # The score produced by `score_parameter_pair_compatibility` is a *composite*
    # over roles, common operations, and (best) commitment-pair compatibility.
    # A score of 1.0 indicates all checks pass; lower scores may still be useful
    # to callers as a signal/diagnostic, but should not be treated as compatible.
    MIN_COMPAT_SCORE: float = 0.7

    @staticmethod
    def check_commitment_pair_compatibility(
        commitment1: CommitmentMetadata,
        commitment2: CommitmentMetadata,
        *,
        operation_type: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Check if two commitments are compatible (optionally op-specific)."""
        if commitment1.data_format != commitment2.data_format:
            return (
                False,
                f"Data format mismatch: {commitment1.data_format} vs {commitment2.data_format}",
            )

        acceptable_freshness = (DataFreshness.REAL_TIME, DataFreshness.DAILY)
        if commitment1.data_freshness not in acceptable_freshness:
            return (
                False,
                f"First commitment data not fresh enough: {commitment1.data_freshness}",
            )
        if commitment2.data_freshness not in acceptable_freshness:
            return (
                False,
                f"Second commitment data not fresh enough: {commitment2.data_freshness}",
            )

        # Industry is a *signal*, not a hard blocker for the generic checker.
        industry_note = ""
        if commitment1.industry != commitment2.industry:
            industry_note = (
                f" (note: industry differs: {commitment1.industry} vs {commitment2.industry})"
            )

        if operation_type == "PSI":
            # Current PSI examples assume structured records.
            if commitment1.data_format != DataFormat.STRUCTURED:
                return False, "PSI requires structured data format"

            # Pragmatic PSI pairing: list-vs-list (customer list vs sanctions/blacklist).
            allowed_structures = {DataStructure.CUSTOMER_LIST, DataStructure.BLACKLIST}
            if (
                commitment1.data_structure not in allowed_structures
                or commitment2.data_structure not in allowed_structures
            ):
                allowed = ", ".join(sorted(s.value for s in allowed_structures))
                return False, f"PSI requires commitments with data_structure in [{allowed}]"

        return True, f"Compatible: aligned format and freshness{industry_note}"

    @dataclass(frozen=True)
    class _CommitmentPairScore:
        score: float
        reason: str
        left_id: str
        right_id: str

    @staticmethod
    def _iter_pairs(
        left: Iterable[CommitmentMetadata], right: Iterable[CommitmentMetadata]
    ) -> Iterable[tuple[CommitmentMetadata, CommitmentMetadata]]:
        for a in left:
            for b in right:
                yield a, b

    @staticmethod
    def _best_commitment_pair(
        left: list[CommitmentMetadata],
        right: list[CommitmentMetadata],
        *,
        operation_type: Optional[str],
    ) -> "CommitmentCompatibilityChecker._CommitmentPairScore":
        best = CommitmentCompatibilityChecker._CommitmentPairScore(
            score=0.0,
            reason="No compatible commitment pair found",
            left_id=left[0].commitment_id if left else "<missing>",
            right_id=right[0].commitment_id if right else "<missing>",
        )
        for c1, c2 in CommitmentCompatibilityChecker._iter_pairs(left, right):
            ok, reason = CommitmentCompatibilityChecker.check_commitment_pair_compatibility(
                c1, c2, operation_type=operation_type
            )
            if ok:
                return CommitmentCompatibilityChecker._CommitmentPairScore(
                    score=1.0,
                    reason=reason,
                    left_id=c1.commitment_id,
                    right_id=c2.commitment_id,
                )
            # Keep the first failure as "best" only to preserve IDs for debugging.
            if best.score == 0.0 and best.reason == "No compatible commitment pair found":
                best = CommitmentCompatibilityChecker._CommitmentPairScore(
                    score=0.0,
                    reason=reason,
                    left_id=c1.commitment_id,
                    right_id=c2.commitment_id,
                )
        return best

    @staticmethod
    def score_parameter_pair_compatibility(
        params1: AP3ExtensionParameters,
        params2: AP3ExtensionParameters,
        *,
        operation_type: Optional[str] = None,
    ) -> Tuple[float, str]:
        """Compatibility scoring with detailed explanation string."""
        score = 0.0
        explanations: list[str] = []

        # Role compatibility (30%)
        if (
            ("ap3_receiver" in params1.roles and "ap3_initiator" in params2.roles)
            or ("ap3_initiator" in params1.roles and "ap3_receiver" in params2.roles)
        ):
            score += 0.3
            explanations.append("PASS: Roles compatible (receiver + initiator)")
        else:
            return 0.0, "FAIL: Roles incompatible - cannot proceed"

        # Operation support (30%)
        common_ops = set(params1.supported_operations) & set(params2.supported_operations)
        if common_ops:
            score += 0.3
            explanations.append(f"PASS: Common operations: {', '.join(sorted(common_ops))}")
        else:
            explanations.append("FAIL: No common operations supported")
            return score, "; ".join(explanations)

        # Commitments (40%) — choose best pair among commitments.
        if not params1.commitments or not params2.commitments:
            explanations.append("FAIL: Missing commitments")
            return score, "; ".join(explanations)

        best = CommitmentCompatibilityChecker._best_commitment_pair(
            list(params1.commitments),
            list(params2.commitments),
            operation_type=operation_type,
        )
        if best.score >= 1.0:
            score += 0.4
            explanations.append(
                f"PASS: Commitments compatible ({best.left_id} ↔ {best.right_id}): {best.reason}"
            )
        else:
            explanations.append(
                f"FAIL: Commitments incompatible (best candidate {best.left_id} ↔ {best.right_id}): {best.reason}"
            )

        return score, "; ".join(explanations)

    @staticmethod
    def is_compatible_score(score: float) -> bool:
        """Return True when the score meets the minimum compatibility bar."""
        return score >= CommitmentCompatibilityChecker.MIN_COMPAT_SCORE
