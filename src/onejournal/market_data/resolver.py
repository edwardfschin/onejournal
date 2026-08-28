"""Credential-free provider-native market-session resolver boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from onejournal.brokers.normalized import NormalizedQuote

from .sessions import (
    ProviderMarketSessionAuthority,
    SessionAuthorityError,
    validate_provider_session_authority_binding,
)


class ProviderMarketSessionResolver(Protocol):
    """Provider-specific implementations resolve already captured evidence.

    Implementations sit behind provider connectors/adapters. This protocol does
    not grant network or credential capability and does not define a fallback.
    """

    def resolve(
        self,
        *,
        quote: NormalizedQuote,
        evaluated_at: datetime,
    ) -> ProviderMarketSessionAuthority:
        """Return same-provider authority for the exact quote assessment."""


def resolve_provider_session_authority(
    resolver: ProviderMarketSessionResolver,
    *,
    quote: NormalizedQuote,
    evaluated_at: datetime,
) -> ProviderMarketSessionAuthority:
    """Resolve and validate authority, failing closed on resolver errors."""

    try:
        authority = resolver.resolve(quote=quote, evaluated_at=evaluated_at)
    except SessionAuthorityError:
        raise
    except Exception as exc:
        raise SessionAuthorityError("provider session resolver failed closed") from exc
    if not isinstance(authority, ProviderMarketSessionAuthority):
        raise SessionAuthorityError(
            "provider session resolver returned an unsupported authority contract"
        )
    validate_provider_session_authority_binding(
        authority,
        quote=quote,
        evaluated_at=evaluated_at,
    )
    return authority
