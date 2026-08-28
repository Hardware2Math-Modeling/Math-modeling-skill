"""Opaque process-local authorization capability for host integrations.

Evidence callers may pass a capability around, but verification behavior is kept in
this module's identity registry.  Objects that merely expose similarly named methods
never enter the registry and therefore cannot authorize anything.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Callable
from weakref import WeakKeyDictionary


# Keep direct script and supported ``scripts.*`` imports on one module object.
# This preserves one capability class, seal, and registry in either import mode.
_THIS_MODULE = sys.modules.get(__name__)
if _THIS_MODULE is not None:
    if __name__ == "authorization_capability":
        sys.modules.setdefault("scripts.authorization_capability", _THIS_MODULE)
    elif __name__ == "scripts.authorization_capability":
        sys.modules.setdefault("authorization_capability", _THIS_MODULE)


class AuthorizationCapabilityError(ValueError):
    """Raised when a value is not a capability installed by the local host."""


class _HostCapability:
    __slots__ = ("__weakref__",)

    def __new__(cls, seal: object) -> _HostCapability:
        if seal is not _CAPABILITY_SEAL:
            raise TypeError("host capabilities can only be installed by the host boundary")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("host capabilities cannot be subclassed")


UserEventVerifier = Callable[..., dict[str, object] | None]
OfficialSourceVerifier = Callable[..., bool]


@dataclass(frozen=True)
class _HostBindings:
    verify_user_event: UserEventVerifier
    verify_official_source: OfficialSourceVerifier


_CAPABILITY_SEAL = object()
_HOST_BINDINGS: WeakKeyDictionary[_HostCapability, _HostBindings] = WeakKeyDictionary()
_HOST_REGISTRATION_TOKEN = object()


def _install_host_capability(
    *,
    verify_user_event: UserEventVerifier,
    verify_official_source: OfficialSourceVerifier,
    registration_token: object | None = None,
) -> object:
    """Install host-owned callbacks and return their opaque process-local handle.

    This deliberately private boundary is for the embedding host and deterministic
    tests.  It supplies no built-in issuer, receipt, source, or accepting verifier.
    """

    if registration_token is not _HOST_REGISTRATION_TOKEN:
        raise AuthorizationCapabilityError(
            "host capability installation requires the embedding-host registration token"
        )
    if not callable(verify_user_event) or not callable(verify_official_source):
        raise TypeError("host verification callbacks must be callable")
    capability = _HostCapability(_CAPABILITY_SEAL)
    _HOST_BINDINGS[capability] = _HostBindings(
        verify_user_event=verify_user_event,
        verify_official_source=verify_official_source,
    )
    return capability


def _bindings(capability: object) -> _HostBindings:
    if type(capability) is not _HostCapability:
        raise AuthorizationCapabilityError(
            "trusted process-local host capability is required"
        )
    bindings = _HOST_BINDINGS.get(capability)
    if bindings is None:
        raise AuthorizationCapabilityError(
            "host capability is not installed in this process"
        )
    return bindings


def verify_user_event(
    capability: object,
    *,
    event_id: object,
    event_type: str,
    challenge_sha256: str,
) -> dict[str, object] | None:
    """Resolve a user-event receipt through an installed host capability."""

    return _bindings(capability).verify_user_event(
        event_id=event_id,
        event_type=event_type,
        challenge_sha256=challenge_sha256,
    )


def verify_official_source(
    capability: object,
    *,
    competition: object,
    source_type: object,
    source_url: object,
    verified_at: object,
    content_sha256: object,
) -> bool:
    """Verify one official-source observation through an installed capability."""

    return _bindings(capability).verify_official_source(
        competition=competition,
        source_type=source_type,
        source_url=source_url,
        verified_at=verified_at,
        content_sha256=content_sha256,
    )


__all__ = [
    "AuthorizationCapabilityError",
    "verify_official_source",
    "verify_user_event",
]
