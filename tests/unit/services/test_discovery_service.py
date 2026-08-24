from ap3.a2a.card import AP3_EXTENSION_URI
from ap3.services.discovery import RemoteAgentDiscoveryService


def test_extract_ap3_params_accepts_current_extension_uri():
    svc = RemoteAgentDiscoveryService()

    card = {
        "capabilities": {
            "extensions": [
                {
                    "uri": AP3_EXTENSION_URI,
                    "params": {
                        "roles": ["ap3_initiator"],
                        "supported_operations": ["PSI"],
                        "commitments": [],
                    },
                }
            ]
        }
    }
    assert svc.extract_ap3_params(card) is not None


def test_extract_ap3_params_rejects_unversioned_legacy_uri():
    # Pre-v1 unversioned URIs are no longer honored: A2A spec requires
    # extension URIs to be versioned, and mixing versions silently would
    # let a peer skip the version handshake.
    svc = RemoteAgentDiscoveryService()

    for legacy in (
        "https://github.com/lfdt-ap3/ap3",
        "https://github.com/lfdt-ap3/ap3/tree/main",
    ):
        card = {
            "capabilities": {
                "extensions": [
                    {
                        "uri": legacy,
                        "params": {
                            "roles": ["ap3_receiver"],
                            "supported_operations": ["PSI"],
                            "commitments": [],
                        },
                    }
                ]
            }
        }
        assert svc.extract_ap3_params(card) is None
