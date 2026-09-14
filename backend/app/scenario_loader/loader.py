from pathlib import Path

import yaml
from pydantic import ValidationError

from app.scenario_loader.exceptions import ScenarioValidationError
from app.scenario_loader.schema import ScenarioConfig


def _format_pydantic_errors(exc: ValidationError) -> list[str]:
    formatted = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        formatted.append(f"{location}: {error['msg']}")
    return formatted


def load_scenario_file(path: Path | str) -> ScenarioConfig:
    """Parse and schema-validate one scenario YAML file. Cross-entity
    validation against a real campus config happens separately (see
    app.services.simulation) since it needs a database session."""

    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ScenarioValidationError([f"{path}: file is empty"])

    try:
        return ScenarioConfig.model_validate(raw)
    except ValidationError as exc:
        raise ScenarioValidationError(_format_pydantic_errors(exc)) from exc
