"""
Network Entity ORM Models

SQLAlchemy models for storing network entities and relationships
in PostgreSQL with JSONB for flexible attributes.

NOTE: Both NetworkEntityORM and EntityRelationshipORM have been moved to
backend.app.models. This module re-exports them for backward compatibility.
"""

# Import canonical ORMs from backend.app.models — do NOT redefine them here.
# Redefining on the same Base causes SQLAlchemy to raise:
#   InvalidRequestError: Table 'X' is already defined for this MetaData instance.
from backend.app.models.network_entity_orm import NetworkEntityORM  # noqa: F401
from backend.app.models.entity_relationship_orm import EntityRelationshipORM  # noqa: F401
