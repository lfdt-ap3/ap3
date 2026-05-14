from ap3.services.discovery import RemoteAgentDiscoveryService


def test_extract_ap3_params_accepts_current_and_legacy_extension_uris():
    svc = RemoteAgentDiscoveryService()

    base = {
        "capabilities": {
            "extensions": [
                {
                    "uri": "https://github.com/lfdt-ap3/ap3",
                    "params": {
                        "roles": ["ap3_initiator"],
                        "supported_operations": ["PSI"],
                        "commitments": [],
                    },
                }
            ]
        }
    }
    assert svc.extract_ap3_params(base) is not None

    legacy = {
        "capabilities": {
            "extensions": [
                {
                    "uri": "https://github.com/lfdt-ap3/ap3/tree/main",
                    "params": {
                        "roles": ["ap3_receiver"],
                        "supported_operations": ["PSI"],
                        "commitments": [],
                    },
                }
            ]
        }
    }
    assert svc.extract_ap3_params(legacy) is not None

