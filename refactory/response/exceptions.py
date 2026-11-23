"""Exceptions for AI response parsing.

``ResponseParser.parse`` never raises for malformed model output — it returns
``PartialReviewResult`` with warnings. These types are for internal signaling
and rare programmer misuse (e.g. invalid constructor args).
"""

from __future__ import annotations

from refactory.core.exceptions import RefactoryError


class ResponseParseError(RefactoryError):
    """Fatal parse error that escapes the best-effort parser (should be rare)."""


class ResponseFormatError(ResponseParseError):
    """Input was present but could not be interpreted as a review document."""
