"""
Unit tests for the PII Scrubber service.
"""
import pytest
from backend.app.services.pii_scrubber import PIIScrubber


@pytest.fixture
def scrubber():
    return PIIScrubber()


def test_scrub_phone_numbers(scrubber):
    """UK (+44) and US (+1) numbers are scrubbed."""
    text = "Call us at +44 7911 123456 or +1 (555) 867-5309"
    scrubbed, manifest = scrubber.scrub(text)
    assert "+44 7911 123456" not in scrubbed
    assert "+1 (555) 867-5309" not in scrubbed
    assert "[PHONE_REDACTED]" in scrubbed
    phone_items = [m for m in manifest if "phone" in m["field_type"]]
    assert len(phone_items) >= 1


def test_scrub_imsi(scrubber):
    """15-digit IMSI is scrubbed."""
    text = "IMSI: 234150012345678 is roaming"
    scrubbed, manifest = scrubber.scrub(text)
    assert "234150012345678" not in scrubbed
    assert "[IMSI_REDACTED]" in scrubbed
    imsi_items = [m for m in manifest if m["field_type"] == "imsi"]
    assert len(imsi_items) == 1


def test_scrub_billing_amounts(scrubber):
    """£, $, € amounts are scrubbed."""
    text = "Customer owes £500.00 and has a credit of $200 and €150"
    scrubbed, manifest = scrubber.scrub(text)
    assert "£500.00" not in scrubbed
    assert "$200" not in scrubbed
    assert "€150" not in scrubbed
    assert "[AMOUNT_REDACTED]" in scrubbed


def test_scrub_ip_addresses(scrubber):
    """IPv4 addresses are scrubbed."""
    text = "Device at 192.168.1.100 connected from 10.0.0.1"
    scrubbed, manifest = scrubber.scrub(text)
    assert "192.168.1.100" not in scrubbed
    assert "10.0.0.1" not in scrubbed
    assert "[IP_REDACTED]" in scrubbed
    ip_items = [m for m in manifest if m["field_type"] == "ipv4"]
    assert len(ip_items) == 2


def test_scrub_manifest_produced(scrubber):
    """Manifest contains hash of original value, not the value itself."""
    text = "Customer: John Smith (IMSI: 234150012345678)"
    scrubbed, manifest = scrubber.scrub(text)
    assert len(manifest) > 0
    for item in manifest:
        assert "original_value_hash" in item
        assert "field_type" in item
        assert "replacement" in item
        # Hash should be hex string, not the original value
        assert "John Smith" not in item["original_value_hash"]
        assert "234150012345678" not in item["original_value_hash"]
        # Hash should be 16 chars (truncated SHA-256)
        assert len(item["original_value_hash"]) == 16


def test_passthrough_topology_metadata(scrubber):
    """Topology terms like 'gNodeB', 'Cell-001' are NOT scrubbed."""
    text = "gNodeB Cell-001 at site Manchester-North is showing high PRB utilization"
    scrubbed, manifest = scrubber.scrub(text)
    assert "gNodeB" in scrubbed
    assert "Cell-001" in scrubbed
    assert "Manchester-North" in scrubbed
    # No items should have been scrubbed
    assert len(manifest) == 0


def test_scrub_subscriber_name(scrubber):
    """Subscriber names after 'Customer:' label are scrubbed."""
    text = "Customer: Jane Doe has complained about service"
    scrubbed, manifest = scrubber.scrub(text)
    assert "Jane Doe" not in scrubbed
    assert "[NAME_REDACTED]" in scrubbed
    # Label should be preserved
    assert "Customer:" in scrubbed


def test_passthrough_fields_config():
    """Fields in pass_through list are not scrubbed."""
    scrubber = PIIScrubber(fields_to_pass_through=["ipv4"])
    text = "IP: 192.168.1.1 and IMSI: 234150012345678"
    scrubbed, manifest = scrubber.scrub(text)
    # IP should NOT be scrubbed
    assert "192.168.1.1" in scrubbed
    # IMSI should still be scrubbed
    assert "234150012345678" not in scrubbed
