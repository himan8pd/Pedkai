"""
TMF642 Alarm Management Models (v4.0)

Pydantic models for standards-compliant alarm exposure.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class PerceivedSeverity(str, Enum):
    """TMF642 Perceived Severity (ITU-T X.733)"""
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    WARNING = "warning"
    INDETERMINATE = "indeterminate"
    CLEARED = "cleared"


class AlarmType(str, Enum):
    """TMF642 Alarm Type (ITU-T X.733)"""
    COMMUNICATIONS = "communicationsAlarm"
    QOS = "qualityOfServiceAlarm"
    PROCESSING = "processingErrorAlarm"
    ENVIRONMENTAL = "environmentalAlarm"
    EQUIPMENT = "equipmentAlarm"


class AlarmState(str, Enum):
    """TMF642 Alarm State"""
    RAISED = "raised"
    UPDATED = "updated"
    CLEARED = "cleared"


class AckState(str, Enum):
    """TMF642 Acknowledge State"""
    ACKNOWLEDGED = "acknowledged"
    UNACKNOWLEDGED = "unacknowledged"


class TMF642AlarmedObject(BaseModel):
    """Reference to the entity that raised the alarm."""
    id: str
    href: Optional[str] = None
    name: Optional[str] = None
    onap_type: Optional[str] = Field(None, alias="@type")


class TMF642Comment(BaseModel):
    """Internal notes on the alarm."""
    id: str
    time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    system_id: str
    text: str
    comment_type: Optional[str] = Field(None, alias="@type")


class TMF642AlarmRef(BaseModel):
    """Lightweight reference to another alarm (for correlation)."""
    id: str
    href: Optional[str] = None
    name: Optional[str] = None


class TMF642Alarm(BaseModel):
    """
    TMF642 Alarm Resource (v4.0.0)
    """
    id: str
    href: Optional[str] = None
    alarmType: AlarmType
    perceivedSeverity: PerceivedSeverity
    probableCause: Optional[str] = None
    specificProblem: Optional[str] = None
    state: AlarmState
    ackState: AckState
    
    eventTime: datetime
    raisedTime: datetime
    reportingSystemId: str = "pedkai"
    sourceSystemId: str = "pedkai"
    
    alarmedObject: TMF642AlarmedObject
    proposedRepairedActions: Optional[str] = None
    
    correlatedAlarm: List[TMF642AlarmRef] = Field(default_factory=list)
    comment: List[TMF642Comment] = Field(default_factory=list)
    
    onap_type: str = Field("Alarm", alias="@type")
    onap_base_type: str = Field("Entity", alias="@baseType")
    onap_schema_location: str = Field(
        "https://raw.githubusercontent.com/tmforum-apis/TMF642_AlarmManagement/master/TMF642_AlarmManagement_v4.0.0.swagger.json",
        alias="@schemaLocation"
    )

    class Config:
        populate_by_name = True


class TMF642AlarmUpdate(BaseModel):
    """Schema for PATCH /alarm/{id}"""
    ackState: Optional[AckState] = None
    state: Optional[AlarmState] = None
    perceivedSeverity: Optional[PerceivedSeverity] = None
    comment: Optional[TMF642Comment] = None
