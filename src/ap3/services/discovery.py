"""Remote agent discovery and AP3 compatibility checking."""

import logging
from typing import Dict, Optional, Tuple

import httpx

from ap3.types import AP3ExtensionParameters
from ap3.services.compatibility import CommitmentCompatibilityChecker

logger = logging.getLogger(__name__)

_AP3_EXTENSION_URIS = (
    # Current canonical URI (used by `ap3.a2a.card.build_privacy_agent_card`)
    "https://github.com/lfdt-ap3/ap3",
    # Legacy URI seen in older docs/examples
    "https://github.com/lfdt-ap3/ap3/tree/main",
)

class RemoteAgentDiscoveryService:
    """Service for discovering and checking compatibility with remote agents.

    Fetches agent cards from remote agents via HTTP and checks their AP3
    compatibility. Provides caching of agent cards and detailed scoring.
    """

    def __init__(self):
        self.agent_cards_cache: Dict[str, dict] = {}

    async def fetch_agent_card(self, agent_url: str) -> Optional[dict]:
        """Fetch agent card from a remote agent's well-known URL.

        Args:
            agent_url: The base URL of the agent

        Returns:
            Agent card dict or None if fetch failed
        """
        try:
            async with httpx.AsyncClient() as client:
                card_url = f"{agent_url.rstrip('/')}/.well-known/agent-card.json"
                response = await client.get(card_url, timeout=10.0)
                response.raise_for_status()
                agent_card = response.json()
                self.agent_cards_cache[agent_url] = agent_card
                return agent_card
        except Exception as e:
            logger.warning("Failed to fetch agent card from %s: %s", agent_url, e)
            return None

    def extract_ap3_params(self, agent_card: dict) -> Optional[AP3ExtensionParameters]:
        """Extract AP3 extension parameters from an agent card.

        Args:
            agent_card: Agent card dictionary

        Returns:
            AP3ExtensionParameters or None if not found
        """
        try:
            capabilities = agent_card.get("capabilities", {})
            extensions = capabilities.get("extensions", [])

            for ext in extensions:
                if ext.get("uri") in _AP3_EXTENSION_URIS:
                    params = ext.get("params", {})
                    return AP3ExtensionParameters.model_validate(params)

            return None
        except Exception as e:
            logger.warning("Failed to extract AP3 params: %s", e)
            return None

    async def check_compatibility(
        self,
        agent_a_url: str,
        agent_b_url: str,
        required_operation: Optional[str] = None,
    ) -> Tuple[bool, float, str, dict]:
        """Check AP3 compatibility between two remote agents.

        Args:
            agent_a_url: URL of the first agent
            agent_b_url: URL of the second agent
            required_operation: Optional specific operation that must be supported

        Returns:
            Tuple of (is_compatible, score, explanation, details_dict)
        """
        card_a = await self.fetch_agent_card(agent_a_url)
        card_b = await self.fetch_agent_card(agent_b_url)

        if not card_a:
            return False, 0.0, f"Failed to fetch agent card from {agent_a_url}", {}

        if not card_b:
            return False, 0.0, f"Failed to fetch agent card from {agent_b_url}", {}

        params_a = self.extract_ap3_params(card_a)
        params_b = self.extract_ap3_params(card_b)

        if not params_a:
            return (
                False,
                0.0,
                f"Agent at {agent_a_url} does not support AP3 extension",
                {"agent_a_card": card_a},
            )

        if not params_b:
            return (
                False,
                0.0,
                f"Agent at {agent_b_url} does not support AP3 extension",
                {"agent_b_card": card_b},
            )

        score, explanation = CommitmentCompatibilityChecker.score_parameter_pair_compatibility(
            params_a, params_b
        )

        if required_operation and score > 0:
            common_ops = set(params_a.supported_operations) & set(params_b.supported_operations)
            if required_operation not in common_ops:
                return (
                    False,
                    0.0,
                    f"Required operation '{required_operation}' not supported by both agents",
                    {
                        "agent_a_card": card_a,
                        "agent_b_card": card_b,
                        "agent_a_ap3": params_a.model_dump(),
                        "agent_b_ap3": params_b.model_dump(),
                    },
                )

        details = {
            "agent_a_card": card_a,
            "agent_b_card": card_b,
            "agent_a_ap3": params_a.model_dump(),
            "agent_b_ap3": params_b.model_dump(),
            "score": score,
            "explanation": explanation,
        }

        is_compatible = CommitmentCompatibilityChecker.is_compatible_score(score)
        return is_compatible, score, explanation, details

    def format_compatibility_report(
        self,
        receiver_url: str,
        initiator_url: str,
        is_compatible: bool,
        score: float,
        explanation: str,
        details: dict,
    ) -> str:
        """Format a human-readable compatibility report."""
        status_icon = "\u2705" if is_compatible else "\u274c"
        status_text = "COMPATIBLE" if is_compatible else "INCOMPATIBLE"

        report = [
            f"{status_icon} AP3 Compatibility Check: {status_text} (Score: {score:.2f}/1.0)",
            f"Receiver: {receiver_url}",
            f"Initiator: {initiator_url}",
            "",
            f"Analysis: {explanation}",
            "",
            "Details:",
        ]

        if "agent_a_ap3" in details and details["agent_a_ap3"]:
            params_a = details["agent_a_ap3"]
            if "commitments" in params_a and params_a["commitments"]:
                comm_a = params_a["commitments"][0]
                report.append(f"- Receiver Commitment: {comm_a.get('commitment_id', 'Unknown')}")

        if "agent_b_ap3" in details and details["agent_b_ap3"]:
            params_b = details["agent_b_ap3"]
            if "commitments" in params_b and params_b["commitments"]:
                comm_b = params_b["commitments"][0]
                report.append(f"- Initiator Commitment: {comm_b.get('commitment_id', 'Unknown')}")

        return "\n".join(report)
