"""Database schema validation helpers."""

from sqlalchemy import inspect


REQUIRED_SCHEMA: dict[str, set[str]] = {
    "player": {
        "id",
        "name",
        "name_normalized",
        "is_active",
        "created_at",
        "venmo_handle",
        "zelle_handle",
        "photo_path_or_url",
        "notes",
        "harper_crew",
    },
    "game": {
        "id",
        "played_at",
        "source_image_path_or_url",
        "created_at",
        "updated_at",
    },
    "game_entry": {
        "id",
        "game_id",
        "player_id",
        "raw_name",
        "buyin",
        "cashout",
        "final_stack",
        "net_change",
        "created_at",
    },
    "settlement": {
        "id",
        "player_id",
        "game_id",
        "settled_at",
        "amount",
        "note",
        "created_at",
    },
    "expense": {
        "id",
        "player_id",
        "amount",
        "note",
        "created_at",
        "expense_group_id",
        "deleted_at",
    },
}


def get_schema_issues(engine) -> list[str]:
    """Return a list of missing tables/columns required by the current app code."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    issues: list[str] = []

    for table_name, required_columns in REQUIRED_SCHEMA.items():
        if table_name not in table_names:
            issues.append(f"missing table: {table_name}")
            continue
        column_names = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = sorted(required_columns - column_names)
        issues.extend(f"missing column: {table_name}.{column_name}" for column_name in missing_columns)

    return issues
