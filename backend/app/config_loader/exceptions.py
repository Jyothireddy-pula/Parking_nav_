class ConfigValidationError(Exception):
    """Raised when a campus configuration file fails structural or
    cross-entity validation. Carries every error found, not just the first."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))
