from .base import EvidenceFusionMethodology, EvidenceProfile
from .noisy_or import NoisyORFusion
from .dempster_shafer import DempsterShaferFusion


class FusionMethodologyFactory:
    """Registry and factory for evidence fusion methodologies.

    Supports named lookup and profile-based automatic selection.
    """

    _registry: dict[str, type[EvidenceFusionMethodology]] = {}

    @classmethod
    def register(cls, name: str, methodology_class: type[EvidenceFusionMethodology]) -> None:
        """Register a fusion methodology class under the given name.

        Args:
            name: Unique string key (e.g. "noisy_or").
            methodology_class: Concrete subclass of EvidenceFusionMethodology.
        """
        cls._registry[name] = methodology_class

    @classmethod
    def create(cls, name: str) -> EvidenceFusionMethodology:
        """Instantiate a registered fusion methodology by name.

        Args:
            name: Key used when the class was registered.

        Returns:
            A new instance of the requested methodology.

        Raises:
            KeyError: If no methodology is registered under that name.
        """
        if name not in cls._registry:
            raise KeyError(
                f"No fusion methodology registered under '{name}'. "
                f"Available: {list(cls._registry.keys())}"
            )
        return cls._registry[name]()

    @classmethod
    def select_for_profile(cls, profile: EvidenceProfile) -> EvidenceFusionMethodology:
        """Return the first registered methodology that declares itself appropriate
        for the given evidence profile.

        Iterates registration order (insertion order in Python 3.7+).

        Args:
            profile: Descriptor of the current evidence context.

        Returns:
            The first appropriate methodology instance.

        Raises:
            RuntimeError: If no registered methodology suits the profile.
        """
        for methodology_class in cls._registry.values():
            instance = methodology_class()
            if instance.is_appropriate_for(profile):
                return instance
        raise RuntimeError(
            f"No registered fusion methodology is appropriate for profile: {profile}. "
            f"Registered methodologies: {list(cls._registry.keys())}"
        )


# Pre-register built-in methodologies
FusionMethodologyFactory.register("noisy_or", NoisyORFusion)
FusionMethodologyFactory.register("dempster_shafer", DempsterShaferFusion)
