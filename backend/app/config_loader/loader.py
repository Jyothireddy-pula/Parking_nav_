from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config_loader.exceptions import ConfigValidationError
from app.config_loader.schema import CampusConfigFile
from app.config_loader.validators import validate_campus_config


def _format_pydantic_errors(exc: ValidationError) -> list[str]:
    formatted = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        formatted.append(f"{location}: {error['msg']}")
    return formatted


def load_campus_config_file(path: Path | str) -> CampusConfigFile:
    """Parse and validate one campus YAML file. Raises ConfigValidationError
    with every problem found (schema-level and cross-entity) rather than
    stopping at the first."""

    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ConfigValidationError([f"{path}: file is empty"])

    try:
        config = CampusConfigFile.model_validate(raw)
    except ValidationError as exc:
        raise ConfigValidationError(_format_pydantic_errors(exc)) from exc

    errors = validate_campus_config(config)
    if errors:
        raise ConfigValidationError(errors)

    return config
