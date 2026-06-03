"""scripts/promote.py — promote MLflow Registry aliases with an audit log.

YOUR TASK (see tasks/task2.md): implement the four subcommand functions.
The argparse scaffolding below is wired so each cmd_* receives an `args`
namespace already parsed. See `_build_parser` for what's on `args` per
subcommand, and tasks/task2.md "Behavioral specs" for what each function
must do.

Versions are identified by their `config_id` tag (e.g., "v6"), NOT by
MLflow's integer version numbers. Resolution must be unique — if the
config_id matches zero or multiple registered versions, the CLI errors
out and forces the operator to disambiguate via the MLflow UI.

Successful `set` and `rollback` operations append a JSON event to
LOG_FILE (promotion-log.jsonl at repo root). `rollback` consults the
log to find the previous alias target.

Subcommands:
  set <alias> <config_id>   move alias, append `set` event to the log
  show <alias>              print current target + tags + key metrics
  list                      print all aliases on the registered model
  rollback <alias>          move alias back per the audit log, append
                            `rollback` event
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import mlflow
from mlflow.exceptions import RestException
from mlflow.tracking import MlflowClient

REGISTERED_MODEL_NAME = "travel-assistant"
LOG_FILE = Path(__file__).resolve().parent.parent / "promotion-log.jsonl"


def _get_client() -> MlflowClient:
    from src.config import get_settings

    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    return MlflowClient()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries: list[dict] = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def _append_log_event(event: dict) -> None:
    record = {"ts": _utc_timestamp(), **event}
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _config_id_from_version(mv) -> str:
    tags = mv.tags or {}
    return tags.get("config_id", "")


def _resolve_version(client: MlflowClient, model_name: str, config_id: str):
    """Return the ModelVersion for config_id, or exit on zero matches."""
    filter_string = (
        f"name = '{model_name}' AND tags.config_id = '{config_id}'"
    )
    versions = client.search_model_versions(filter_string)
    if not versions:
        print(f"error: no version found with config_id={config_id}")
        sys.exit(1)
    if len(versions) == 1:
        return versions[0]
    sorted_versions = sorted(versions, key=lambda v: int(v.version))
    version_nums = [int(v.version) for v in sorted_versions]
    latest = sorted_versions[-1]
    print(
        f"warning: multiple versions match config_id={config_id} "
        f"(MLflow versions {version_nums}); using latest ({latest.version})"
    )
    return latest


def _current_config_id(client: MlflowClient, model_name: str, alias: str) -> str:
    try:
        mv = client.get_model_version_by_alias(model_name, alias)
    except RestException:
        return ""
    return _config_id_from_version(mv)


def _format_from_label(config_id: str) -> str:
    return "(unset)" if config_id == "" else config_id


def cmd_set(args: argparse.Namespace) -> None:
    """args.alias: str, args.config_id: str. See tasks/task2.md → cmd_set."""
    client = _get_client()
    target = _resolve_version(client, args.name, args.config_id)
    current = _current_config_id(client, args.name, args.alias)
    client.set_registered_model_alias(
        args.name, args.alias, int(target.version)
    )
    _append_log_event(
        {
            "alias": args.alias,
            "from": current,
            "to": args.config_id,
            "op": "set",
        }
    )
    print(f"{args.alias}: {_format_from_label(current)} → {args.config_id}")


def cmd_show(args: argparse.Namespace) -> None:
    """args.alias: str. See tasks/task2.md → cmd_show."""
    client = _get_client()
    try:
        mv = client.get_model_version_by_alias(args.name, args.alias)
    except RestException:
        print(f"error: alias {args.alias!r} is not set on {args.name!r}")
        sys.exit(1)

    tags = mv.tags or {}
    print(f"{args.name} @ {args.alias}")
    print(f"  config_id: {tags.get('config_id', '')}")
    if "model" in tags:
        print(f"  model: {tags['model']}")

    run = client.get_run(mv.run_id)
    metrics = run.data.metrics or {}
    if "accuracy_overall" in metrics:
        print(f"  accuracy_overall: {metrics['accuracy_overall']}")
    if "verdict_rate_leaked" in metrics:
        print(f"  verdict_rate_leaked: {metrics['verdict_rate_leaked']}")
    if "total_cost_usd" in metrics:
        print(f"  total_cost_usd: ${metrics['total_cost_usd']:.2f}")


def cmd_list(args: argparse.Namespace) -> None:
    """No args. See tasks/task2.md → cmd_list."""
    client = _get_client()
    registered = client.get_registered_model(args.name)
    aliases = registered.aliases or {}
    if not aliases:
        print("no aliases set")
        return

    rows: list[tuple[str, str]] = []
    for alias_name in sorted(aliases):
        version_num = aliases[alias_name]
        mv = client.get_model_version(args.name, version_num)
        rows.append((alias_name, _config_id_from_version(mv)))

    width = max(len(alias_name) for alias_name, _ in rows)
    for alias_name, config_id in rows:
        print(f"{alias_name.ljust(width)} -> {config_id}")


def cmd_rollback(args: argparse.Namespace) -> None:
    """args.alias: str. See tasks/task2.md → cmd_rollback."""
    client = _get_client()
    try:
        current_mv = client.get_model_version_by_alias(args.name, args.alias)
    except RestException:
        print("nothing to roll back")
        sys.exit(1)

    current_config_id = _config_id_from_version(current_mv)

    history = [e for e in reversed(_read_log()) if e.get("alias") == args.alias]
    if not history:
        print(f"no promotion history for alias {args.alias}")
        sys.exit(1)

    entry = history[0]
    if entry.get("op") == "rollback":
        print(
            f"error: {args.alias} was just rolled back; "
            "no further history to walk back to"
        )
        sys.exit(1)
    if entry.get("op") == "set" and not entry.get("from"):
        print(
            f"error: {args.alias} has no previous target (first promotion ever)"
        )
        sys.exit(1)

    target_config_id = entry["from"]
    target = _resolve_version(client, args.name, target_config_id)
    client.set_registered_model_alias(
        args.name, args.alias, int(target.version)
    )
    _append_log_event(
        {
            "alias": args.alias,
            "from": current_config_id,
            "to": target_config_id,
            "op": "rollback",
        }
    )
    print(
        f"{args.alias}: {current_config_id} → {target_config_id} (rolled back)"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--name",
        default=REGISTERED_MODEL_NAME,
        help=f"Registered model name (default: {REGISTERED_MODEL_NAME})",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_set = sub.add_parser(
        "set", help="Move an alias to a version (by config_id), append a set event"
    )
    p_set.add_argument("alias", help="Alias to assign (e.g., 'production')")
    p_set.add_argument(
        "config_id",
        help="Config identifier (e.g., 'v6') — resolved via the config_id tag on registered versions",
    )
    p_set.set_defaults(func=cmd_set)

    p_show = sub.add_parser("show", help="Show which version an alias points at")
    p_show.add_argument("alias")
    p_show.set_defaults(func=cmd_show)

    p_list = sub.add_parser("list", help="List all aliases on the registered model")
    p_list.set_defaults(func=cmd_list)

    p_rollback = sub.add_parser(
        "rollback",
        help="Move an alias back to its previous target per the audit log",
    )
    p_rollback.add_argument("alias")
    p_rollback.set_defaults(func=cmd_rollback)

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        args.func(args)
    except NotImplementedError as exc:
        print(f"NOT IMPLEMENTED: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
