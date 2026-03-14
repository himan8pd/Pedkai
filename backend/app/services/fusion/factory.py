from .base import EvidenceFusionMethodology, EvidenceProfile
from .noisy_or import NoisyORFusion
from .dempster_shafer import DempsterShaferFusion


class FusionMethodologyFactory:
    """Registry and factory for evidence fusion methodologies.

    Supports named lookup and profile-based automatic selection.

    Selection order: custom-registered methodologies are checked before
    built-in ones, so domain-specific overrides always take precedence.
    """

    _registry: dict[str, type[EvidenceFusionMethodology]] = {}
    _builtins: set[str] = set()  # names registered as built-in defaults

    @classmethod
    def register(
        cls,
        name: str,
        methodology_class: type[EvidenceFusionMethodology],
        _builtin: bool = False,
    ) -> None:
        """Register a fusion methodology class under the given name.

        Custom registrations are inserted before built-in methodologies so
        that they take priority in ``select_for_profile``.

        Args:
            name: Unique string key (e.g. "noisy_or").
            methodology_class: Concrete subclass of EvidenceFusionMethodology.
            _builtin: Internal flag; True for the pre-registered defaults.
        """
        if _builtin:
            cls._registry[name] = methodology_class
            cls._builtins.add(name)
        else:
            # Insert custom class before built-ins so it is checked first.
            custom = {k: v for k, v in cls._registry.items() if k not in cls._builtins}
            builtins = {k: v for k, v in cls._registry.items() if k in cls._builtins}
            custom[name] = methodology_class
            cls._registry = {**custom, **builtins}

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


# Pre-register built-in methodologies (marked as built-ins so custom
# registrations are always inserted before them in select_for_profile).
FusionMethodologyFactory.register("noisy_or", NoisyORFusion, _builtin=True)
FusionMethodologyFactory.register("dempster_shafer", DempsterShaferFusion, _builtin=True)
