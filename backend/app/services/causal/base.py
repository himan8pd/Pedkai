from abc import ABC, abstractmethod
from dataclasses import dataclass
import numpy as np


@dataclass
class CausalResult:
    score: float       # Transfer entropy or Granger statistic
    p_value: float     # Significance
    is_causal: bool    # True if p_value < alpha
    method: str        # "granger" or "transfer_entropy"


class CausalInferenceMethod(ABC):
    @abstractmethod
    def compute(self, x: np.ndarray, y: np.ndarray, lag: int) -> CausalResult:
        """Test whether x Granger-causes / TE-causes y."""
        pass
