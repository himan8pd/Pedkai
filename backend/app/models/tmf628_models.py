"""
TMF628 Performance Management Models (v4.0)

Pydantic models for standards-compliant performance metrics.
"""

from datetime import datetime
from typing import Optional, List, Union
from enum import Enum

from pydantic import BaseModel, Field


class PerformanceIndicatorSpecificationRef(BaseModel):
    """Reference to a performance indicator specification."""
    id: str
    href: Optional[str] = None
    name: Optional[str] = None


class PerformanceMeasurement(BaseModel):
    """
    TMF628 Performance Measurement (v4.0.0)
    Represents an individual KPI data point.
    """
    id: str
    href: Optional[str] = None
    observationTime: datetime
    measurementValue: Union[float, int, str]
    performanceIndicatorSpecification: PerformanceIndicatorSpecificationRef
    
    # Contextual info (Vendor-specific extension)
    onap_type: str = Field("PerformanceMeasurement", alias="@type")
    
    class Config:
        populate_by_name = True


class PerformanceIndicatorSpecification(BaseModel):
    """
    TMF628 Performance Indicator Specification (v4.0.0)
    Describes a type of metric (e.g., 'Throughput').
    """
    id: str
    href: Optional[str] = None
    name: str
    description: Optional[str] = None
    unitOfMeasure: Optional[str] = None
    onap_type: str = Field("PerformanceIndicatorSpecification", alias="@type")

    class Config:
        populate_by_name = True


class PerformanceMeasurementGroup(BaseModel):
    """Group of measurements for a specific entity."""
    measurementGroupType: str
    performanceMeasurement: List[PerformanceMeasurement]
