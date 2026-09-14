class ScenarioValidationError(Exception):
    """Raised when a simulation scenario file fails structural or
    cross-entity validation. Carries every error found, not just the
    first."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))
