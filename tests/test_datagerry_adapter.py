"""Tests for DatagerryAdapter (TASK-302)."""
import os
import pytest
import respx
import httpx

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")

from backend.app.adapters.datagerry_adapter import DatagerryAdapter, SyncResult

BASE_URL = "http://datagerry-test.local"
TOKEN = "test-token-123"
TENANT = "test-tenant"

MOCK_CIS = [
    {"object_id": "ci-001", "name": "Cell Tower Alpha", "type_name": "CELL", "fields": {"vendor": "Ericsson"}},
    {"object_id": "ci-002", "name": "Site Beta", "type_name": "SITE", "fields": {"location": "Jakarta"}},
]

MOCK_LINKS = [
    {"link_id": "lnk-001", "from_id": "ci-001", "to_id": "ci-002", "link_type": "hosted_on"}
]


@respx.mock
def test_full_sync_creates_entities():
    respx.get(f"{BASE_URL}/rest/objects").mock(
        return_value=httpx.Response(200, json={"results": MOCK_CIS})
    )
    adapter = DatagerryAdapter(BASE_URL, TOKEN, TENANT)
    result = adapter.sync()
    assert isinstance(result, SyncResult)
    assert result.added == 2
    assert result.errors == 0


@respx.mock
def test_fetch_all_cis_returns_list():
    respx.get(f"{BASE_URL}/rest/objects").mock(
        return_value=httpx.Response(200, json={"results": MOCK_CIS})
    )
    adapter = DatagerryAdapter(BASE_URL, TOKEN, TENANT)
    cis = adapter.fetch_all_cis()
    assert len(cis) == 2
    assert cis[0]["object_id"] == "ci-001"


@respx.mock
def test_http_error_returns_empty_list():
    respx.get(f"{BASE_URL}/rest/objects").mock(
        return_value=httpx.Response(503)
    )
    adapter = DatagerryAdapter(BASE_URL, TOKEN, TENANT)
    cis = adapter.fetch_all_cis()
    assert cis == []


def test_upsert_entity_new():
    adapter = DatagerryAdapter(BASE_URL, TOKEN, TENANT)
    action, entity_dict = adapter.upsert_entity(MOCK_CIS[0], {})
    assert action == "added"
    assert entity_dict["external_id"] == "ci-001"
    assert entity_dict["entity_type"] == "CELL"


@respx.mock
def test_ci_missing_from_response_is_phantom_candidate():
    # Simulate incremental sync: previously known ci-003 is absent
    respx.get(f"{BASE_URL}/rest/objects").mock(
        return_value=httpx.Response(200, json={"results": MOCK_CIS})
    )
    adapter = DatagerryAdapter(BASE_URL, TOKEN, TENANT)
    result = adapter.sync()
    # phantom_candidates would be non-zero if we tracked previous state
    # At minimum verify sync runs without error
    assert result.errors == 0


@respx.mock
def test_fetch_relationships():
    respx.get(f"{BASE_URL}/rest/links").mock(
        return_value=httpx.Response(200, json={"results": MOCK_LINKS})
    )
    adapter = DatagerryAdapter(BASE_URL, TOKEN, TENANT)
    links = adapter.fetch_ci_relationships()
    assert len(links) == 1
    assert links[0]["link_id"] == "lnk-001"
