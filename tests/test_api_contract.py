"""Keep the documented HTTP route contract synchronized with FastAPI OpenAPI."""

from pathlib import Path

from agenticos.api.main import create_app
from agenticos.config import Settings


def test_documented_routes_match_generated_openapi(fake_model, tmp_path) -> None:
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
    )
    schema = create_app(settings, model_client=fake_model).openapi()

    actual = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }

    reference = Path(__file__).resolve().parents[1] / "docs" / "api-reference.md"
    documented = set()
    for line in reference.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0].upper() not in {
            "GET", "POST", "PUT", "PATCH", "DELETE"
        }:
            continue
        path = cells[1].strip("`").split("?", maxsplit=1)[0]
        documented.add((cells[0].upper(), path))

    assert documented == actual, (
        f"Routes missing from docs: {sorted(actual - documented)}; "
        f"documented routes missing from OpenAPI: {sorted(documented - actual)}"
    )
