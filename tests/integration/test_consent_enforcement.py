"""
Integration tests for GDPR Consent Enforcement (Phase 0.6).

Verifies that proactive communications are only sent to customers with explicit consent.
"""

import pytest
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import select

from backend.app.models.customer_orm import CustomerORM, ProactiveCareORM
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.cx_intelligence import CXIntelligenceService
from backend.app.core.database import get_db_context


@pytest.mark.asyncio
async def test_trigger_proactive_care_respects_consent():
    """
    Verify that trigger_proactive_care() only sends notifications to customers
    with consent_proactive_comms = True.
    
    Setup:
    - Create 3 customers: 1 with consent, 2 without
    - Call trigger_proactive_care with all 3 customer IDs
    - Assert: only the 1 consenting customer receives a notification
    """
    async with get_db_context() as session:
        # 1. Create test customers
        consenting_customer = CustomerORM(
            id=uuid4(),
            external_id="CUSTOMER_001_CONSENTING",
            name="Consenting Customer",
            churn_risk_score=0.8,
            associated_site_id="SITE_001",
            consent_proactive_comms=True,  # HAS CONSENT
            tenant_id="test-tenant"
        )
        
        non_consenting_customer1 = CustomerORM(
            id=uuid4(),
            external_id="CUSTOMER_002_NO_CONSENT",
            name="Non-Consenting Customer 1",
            churn_risk_score=0.7,
            associated_site_id="SITE_001",
            consent_proactive_comms=False,  # NO CONSENT
            tenant_id="test-tenant"
        )
        
        non_consenting_customer2 = CustomerORM(
            id=uuid4(),
            external_id="CUSTOMER_003_NO_CONSENT",
            name="Non-Consenting Customer 2",
            churn_risk_score=0.75,
            associated_site_id="SITE_002",
            consent_proactive_comms=False,  # NO CONSENT
            tenant_id="test-tenant"
        )
        
        session.add(consenting_customer)
        session.add(non_consenting_customer1)
        session.add(non_consenting_customer2)
        await session.commit()
        
        # 2. Create a test anomaly (DecisionTrace) to link to proactive care records
        anomaly = DecisionTraceORM(
            id=uuid4(),
            tenant_id="test-tenant",
            trigger_type="alarm",
            trigger_description="Test anomaly for consent enforcement",
            decision_summary="Test decision",
            action_taken="test_action",
            decision_maker="test_automation",
            domain="anops"
        )
        session.add(anomaly)
        await session.commit()
        
        # 3. Call trigger_proactive_care with all three customers
        service = CXIntelligenceService(session_factory=get_db_context)
        result = await service.trigger_proactive_care(
            customer_ids=[
                consenting_customer.id,
                non_consenting_customer1.id,
                non_consenting_customer2.id
            ],
            anomaly_id=anomaly.id,
            session=session
        )
        
        # 4. Assertions
        assert result["sent_count"] == 1, f"Expected 1 notification sent, got {result['sent_count']}"
        assert result["blocked_count"] == 2, f"Expected 2 notifications blocked, got {result['blocked_count']}"
        
        # Verify only the consenting customer has a record
        sent_records = result["sent"]
        assert len(sent_records) == 1
        assert sent_records[0].customer_id == consenting_customer.id
        
        # Verify blocked customers are listed
        blocked = result["blocked"]
        blocked_ids = [b["customer_id"] for b in blocked]
        assert str(non_consenting_customer1.id) in blocked_ids
        assert str(non_consenting_customer2.id) in blocked_ids
        
        # Verify the reason is "no_consent"
        for blocked_entry in blocked:
            if blocked_entry["customer_id"] == str(non_consenting_customer1.id):
                assert blocked_entry["reason"] == "no_consent"
            if blocked_entry["customer_id"] == str(non_consenting_customer2.id):
                assert blocked_entry["reason"] == "no_consent"


@pytest.mark.asyncio
async def test_trigger_proactive_care_logs_blocked_customers():
    """
    Verify that non-consenting customers are logged as blocked, not silently skipped.
    """
    async with get_db_context() as session:
        # Create one non-consenting customer
        customer = CustomerORM(
            id=uuid4(),
            external_id="CUSTOMER_BLOCKED_001",
            name="Blocked Customer",
            churn_risk_score=0.6,
            associated_site_id="SITE_001",
            consent_proactive_comms=False,  # NO CONSENT
            tenant_id="test-tenant"
        )
        session.add(customer)
        
        # Create anomaly
        anomaly = DecisionTraceORM(
            id=uuid4(),
            tenant_id="test-tenant",
            trigger_type="alarm",
            trigger_description="Test anomaly for blocked customer",
            decision_summary="Test decision",
            action_taken="test_action",
            decision_maker="test_automation",
            domain="anops"
        )
        session.add(anomaly)
        await session.commit()
        
        # Call service
        service = CXIntelligenceService(session_factory=get_db_context)
        result = await service.trigger_proactive_care(
            customer_ids=[customer.id],
            anomaly_id=anomaly.id,
            session=session
        )
        
        # Should return blocked record
        assert result["sent_count"] == 0
        assert result["blocked_count"] == 1
        assert result["blocked"][0]["customer_id"] == str(customer.id)
        assert result["blocked"][0]["reason"] == "no_consent"


@pytest.mark.asyncio
async def test_trigger_proactive_care_with_nonexistent_customer():
    """
    Verify that non-existent customer IDs are handled gracefully with a "not_found" reason.
    """
    async with get_db_context() as session:
        # Create anomaly
        anomaly = DecisionTraceORM(
            id=uuid4(),
            tenant_id="test-tenant",
            trigger_type="alarm",
            trigger_description="Test anomaly with nonexistent customer",
            decision_summary="Test decision",
            action_taken="test_action",
            decision_maker="test_automation",
            domain="anops"
        )
        session.add(anomaly)
        await session.commit()
        
        # Use a non-existent customer ID
        fake_customer_id = uuid4()
        
        # Call service
        service = CXIntelligenceService(session_factory=get_db_context)
        result = await service.trigger_proactive_care(
            customer_ids=[fake_customer_id],
            anomaly_id=anomaly.id,
            session=session
        )
        
        # Should indicate the customer was not found
        assert result["sent_count"] == 0
        assert result["blocked_count"] == 1
        assert result["blocked"][0]["customer_id"] == str(fake_customer_id)
        assert result["blocked"][0]["reason"] == "not_found"


@pytest.mark.asyncio
async def test_proactive_care_record_created_only_for_consenting():
    """
    End-to-end verification: Only consenting customers should have
    ProactiveCareORM records in the database.
    """
    async with get_db_context() as session:
        # Create customers
        consenting = CustomerORM(
            id=uuid4(),
            external_id="E2E_CONSENTING_001",
            name="E2E Consenting",
            churn_risk_score=0.8,
            consent_proactive_comms=True,
            tenant_id="test-tenant"
        )
        non_consenting = CustomerORM(
            id=uuid4(),
            external_id="E2E_NO_CONSENT_001",
            name="E2E Non-Consenting",
            churn_risk_score=0.7,
            consent_proactive_comms=False,
            tenant_id="test-tenant"
        )
        session.add(consenting)
        session.add(non_consenting)
        
        # Create anomaly
        anomaly = DecisionTraceORM(
            id=uuid4(),
            tenant_id="test-tenant",
            trigger_type="alarm",
            trigger_description="E2E test anomaly",
            decision_summary="Test decision",
            action_taken="test_action",
            decision_maker="test_automation",
            domain="anops"
        )
        session.add(anomaly)
        await session.commit()
        
        # Trigger proactive care
        service = CXIntelligenceService(session_factory=get_db_context)
        await service.trigger_proactive_care(
            customer_ids=[consenting.id, non_consenting.id],
            anomaly_id=anomaly.id,
            session=session
        )
        
        # Query the database directly to verify only the consenting customer has records
        stmt = select(ProactiveCareORM).where(
            ProactiveCareORM.anomaly_id == anomaly.id
        )
        result = await session.execute(stmt)
        care_records = result.scalars().all()
        
        # Should only have 1 record (for consenting customer)
        assert len(care_records) == 1
        assert care_records[0].customer_id == consenting.id
        assert care_records[0].status == "sent"
