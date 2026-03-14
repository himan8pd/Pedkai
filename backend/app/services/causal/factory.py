from .base import CausalInferenceMethod
from .granger import GrangerMethod
from .transfer_entropy import TransferEntropyMethod
from .pcmci_method import PCMCIMethod


class CausalMethodFactory:
    """Registry and factory for causal inference methods.

    Mirrors the FusionMethodologyFactory pattern: supports named lookup
    via a class-level registry with pre-registered built-in methods.
    """

    _registry: dict[str, type[CausalInferenceMethod]] = {}

    @classmethod
    def register(cls, name: str, method_class: type[CausalInferenceMethod]) -> None:
        """Register a causal inference method class under the given name.

        Args:
            name: Unique string key (e.g. "granger", "transfer_entropy").
            method_class: Concrete subclass of CausalInferenceMethod.
        """
        cls._registry[name] = method_class

    @classmethod
    def create(cls, name: str) -> CausalInferenceMethod:
        """Instantiate a registered causal inference method by name.

        Args:
            name: Key used when the class was registered.

        Returns:
            A new instance of the requested method.

        Raises:
            KeyError: If no method is registered under that name.
        """
        if name not in cls._registry:
            raise KeyError(
                f"No causal method registered under '{name}'. "
                f"Available: {list(cls._registry.keys())}"
            )
        return cls._registry[name]()

    @classmethod
    def available(cls) -> list[str]:
        """Return the list of registered method names."""
        return list(cls._registry.keys())


# Pre-register built-in methods
CausalMethodFactory.register("granger", GrangerMethod)
CausalMethodFactory.register("transfer_entropy", TransferEntropyMethod)
CausalMethodFactory.register("pcmci", PCMCIMethod)
