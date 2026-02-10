"""
Alarm Normalizer

Translates vendor-specific alarm formats (Ericsson, Nokia) into 
a unified Pedkai signal format.
"""

from typing import Any, Dict, Optional
import xml.etree.ElementTree as ET
import json


class AlarmNormalizer:
    """
    Normalizes multi-vendor alarms into a common internal format.
    Fulfills Component 3 of Phase 3 implementation.
    """

    def normalize(self, raw_data: Any, vendor: str) -> Dict[str, Any]:
        """
        Main entry point for normalization.
        """
        if vendor.lower() == "ericsson":
            return self._normalize_ericsson(raw_data)
        elif vendor.lower() == "nokia":
            return self._normalize_nokia(raw_data)
        else:
            return self._normalize_generic(raw_data)

    def _normalize_ericsson(self, raw_data: str) -> Dict[str, Any]:
        """
        Parses Ericsson ENM-style XML alarms.
        """
        try:
            # Simple XML parsing for prototype
            root = ET.fromstring(raw_data)
            
            # Map XML fields to Pedkai format
            # Ericsson usually has <specificProblem>, <probableCause>, etc.
            return {
                "event_id": root.findtext("alarmId") or "unknown",
                "entity_id": root.findtext("managedObjectInstance") or "unknown",
                "event_type": root.findtext("eventType") or "equipmentAlarm",
                "severity": self._map_severity(root.findtext("perceivedSeverity")),
                "description": root.findtext("specificProblem") or "No description",
                "probable_cause": root.findtext("probableCause"),
                "external_correlation_id": root.findtext("correlationId"),
                "source": "ERICSSON_ENM"
            }
        except Exception as e:
            print(f"❌ Error normalizing Ericsson alarm: {e}")
            return self._normalize_generic(raw_data)

    def _normalize_nokia(self, raw_data: bytes) -> Dict[str, Any]:
        """
        Parses Nokia NetAct-style JSON alarms.
        """
        try:
            data = json.loads(raw_data)
            # Nokia uses different fields, e.g., notificationType, sourceIndicator
            return {
                "event_id": data.get("alarmId") or "unknown",
                "entity_id": data.get("sourceIndicator") or "unknown",
                "event_type": data.get("notificationType") or "processingErrorAlarm",
                "severity": self._map_severity(data.get("severity")),
                "description": data.get("alarmText") or "No description",
                "probable_cause": data.get("probableCause"),
                "external_correlation_id": data.get("correlationId"),
                "source": "NOKIA_NETACT"
            }
        except Exception as e:
            print(f"❌ Error normalizing Nokia alarm: {e}")
            return self._normalize_generic(raw_data)

    def _normalize_generic(self, raw_data: Any) -> Dict[str, Any]:
        """Fallback for unknown formats."""
        return {
            "description": str(raw_data),
            "source": "GENERIC_NMS",
            "severity": "minor"
        }

    def _map_severity(self, vendor_severity: Optional[str]) -> str:
        """
        Maps vendor-specific severity strings to Pedkai's internal levels.
        """
        if not vendor_severity:
            return "minor"
            
        v = vendor_severity.lower()
        if "crit" in v or "major" in v:
            return "critical"
        if "minor" in v or "warn" in v:
            return "warning"
        if "clear" in v:
            return "cleared"
            
        return "minor"
