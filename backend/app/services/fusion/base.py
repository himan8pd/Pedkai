from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EvidenceProfile:
    source_count: int
    is_sparse: bool
    has_qualitative_assessments: bool
    has_rich_telemetry: bool


class EvidenceFusionMethodology(ABC):
    @abstractmethod
    def combine(self, evidence_probabilities: list[float]) -> float:
        """Combine independent evidence probabilities into a single hypothesis confidence."""
        pass

    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def is_appropriate_for(self, evidence_profile: EvidenceProfile) -> bool:
        pass
