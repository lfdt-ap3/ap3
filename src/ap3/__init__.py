"""File Notes:
- AP3 core SDK exports operation contract only.
- Protocol implementations are expected in external packages.
- Each Operation instance owns its own session state — no registry needed.
"""

from ap3.core import Operation, OperationResult, OperationInputs
from ap3.types import PrivacyIntentDirective, PrivacyResultDirective, PrivacyError, PrivacyViolationError
from ap3.services import CommitmentMetadataSystem, CommitmentCompatibilityChecker, RemoteAgentDiscoveryService
from ap3 import signing

__version__ = "1.2.1"
__all__ = [
    "Operation",
    "OperationResult",
    "OperationInputs",
    "PrivacyIntentDirective",
    "PrivacyResultDirective",
    "PrivacyError",
    "PrivacyViolationError",
    "CommitmentMetadataSystem",
    "CommitmentCompatibilityChecker",
    "RemoteAgentDiscoveryService",
    "signing",
]
