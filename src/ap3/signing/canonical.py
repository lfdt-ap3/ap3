"""Canonical JSON encoding for signature inputs.

AP3 signatures must be stable across runtimes and languages. For that, we need a
deterministic byte representation of the signed fields.

This module implements a strict, deterministic JSON encoding intended to be
compatible with RFC 8785 (JCS) expectations for the subset of types AP3 uses
(objects, arrays, strings, booleans, null, integers).

NOTE: Floating-point canonicalization is tricky to fully standardize across
languages. AP3 should avoid floats in signed payloads where possible.
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Return canonical JSON bytes for signing/verifying.

    Properties:
    - UTF-8
    - Object keys sorted
    - No insignificant whitespace
    - No NaN/Infinity
    - Unicode preserved (no ASCII escaping)
    """
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")

