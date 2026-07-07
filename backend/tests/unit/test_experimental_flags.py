"""CLN-02 — Experimental feature flags for unvalidated discovery mechanisms.

Verifies that the four experimental mechanisms (meta_memory, counterfactual_sim,
expectation_violation, pattern_compressor) are gated behind the
ABEYANCE_EXPERIMENTAL_MECHANISMS env flag:

  - default env  => _DisabledMechanism stubs, all methods awaitable/benign
  - named in env => the real service is constructed
"""

import inspect

import pytest

from backend.app.services.abeyance import (
    EXPERIMENTAL_MECHANISMS,
    _DisabledMechanism,
    create_abeyance_services,
)
from backend.app.services.abeyance.discovery.meta_memory import MetaMemoryService

EXPERIMENTAL_KEYS = [
    "meta_memory",
    "counterfactual_sim",
    "expectation_violation",
    "pattern_compressor",
]


def test_default_env_yields_stubs(monkeypatch):
    """With no env flag set, all four experimental keys are disabled stubs."""
    monkeypatch.delenv("ABEYANCE_EXPERIMENTAL_MECHANISMS", raising=False)
    services = create_abeyance_services()
    for key in EXPERIMENTAL_KEYS:
        assert isinstance(services[key], _DisabledMechanism), (
            f"{key} should be a _DisabledMechanism stub by default"
        )


def test_empty_env_yields_stubs(monkeypatch):
    """An explicitly empty flag disables everything, same as unset."""
    monkeypatch.setenv("ABEYANCE_EXPERIMENTAL_MECHANISMS", "")
    services = create_abeyance_services()
    for key in EXPERIMENTAL_KEYS:
        assert isinstance(services[key], _DisabledMechanism)


def test_experimental_key_set_matches():
    """The canonical set names exactly the four experimental mechanisms."""
    assert set(EXPERIMENTAL_MECHANISMS) == set(EXPERIMENTAL_KEYS)


@pytest.mark.asyncio
async def test_stub_methods_are_awaitable_and_benign():
    """Every stubbed mechanism method is async and returns a benign value.

    dict-returning methods (compute_bias/run_batch) must return {} because the
    discovery loop consumes them via len(...).
    """
    stub = _DisabledMechanism("meta_memory")

    # dict-returning (consumed via len() in discovery_loop)
    assert await stub.compute_bias(None, "t") == {}
    assert await stub.run_batch(None, "t") == {}

    # bool / None-returning
    assert await stub.check_activation(None, "t") is False
    assert await stub.record_outcome(None, "t", "d", "a", True) is None
    assert await stub.enqueue_candidate(None, "t", "fid") is None
    assert await stub.check_transition(None, "t") is None
    assert await stub.analyze(None, "t", "PROFILE") is None

    # confirm the methods are genuinely coroutine functions
    for name in (
        "compute_bias",
        "check_activation",
        "record_outcome",
        "run_batch",
        "enqueue_candidate",
        "check_transition",
        "analyze",
    ):
        assert inspect.iscoroutinefunction(getattr(stub, name)), (
            f"{name} must be an async method"
        )


def test_named_mechanism_enables_for_real(monkeypatch):
    """Naming a mechanism in the env constructs the real service."""
    monkeypatch.setenv("ABEYANCE_EXPERIMENTAL_MECHANISMS", "meta_memory")
    services = create_abeyance_services()

    assert isinstance(services["meta_memory"], MetaMemoryService)
    assert not isinstance(services["meta_memory"], _DisabledMechanism)

    # The others remain disabled stubs.
    for key in ("counterfactual_sim", "expectation_violation", "pattern_compressor"):
        assert isinstance(services[key], _DisabledMechanism)


def test_multiple_named_mechanisms(monkeypatch):
    """CSV parsing enables multiple mechanisms; whitespace is tolerated."""
    monkeypatch.setenv(
        "ABEYANCE_EXPERIMENTAL_MECHANISMS", "meta_memory, pattern_compressor"
    )
    services = create_abeyance_services()

    assert not isinstance(services["meta_memory"], _DisabledMechanism)
    assert not isinstance(services["pattern_compressor"], _DisabledMechanism)
    assert isinstance(services["counterfactual_sim"], _DisabledMechanism)
    assert isinstance(services["expectation_violation"], _DisabledMechanism)
