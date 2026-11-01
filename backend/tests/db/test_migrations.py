"""Tests for C05 db.migrations — Alembic wired to the same metadata.

Behavioural tests run Alembic against a temporary copy of the migration
tree and a file-based SQLite database, so no PostgreSQL server is needed.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, Table

from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_cfg(tmp_path, monkeypatch):
    """In-memory Alembic config over a tmp copy of the migration tree."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutil.copytree(BACKEND_DIR / "alembic", tmp_path / "alembic")
    cfg = Config()
    cfg.set_main_option("script_location", str(tmp_path / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'test.db'}")
    return cfg


def test_upgrade_head_produces_schema(alembic_cfg, tmp_path):
    """`alembic upgrade head` runs cleanly against an empty database."""
    command.upgrade(alembic_cfg, "head")

    script = ScriptDirectory.from_config(alembic_cfg)
    assert script.get_current_head() is not None


def test_autogenerate_produces_reviewable_diff(alembic_cfg, tmp_path):
    """`alembic revision --autogenerate` writes a migration file with the diff."""
    table = Table("probe", Base.metadata, Column("id", Integer, primary_key=True))
    try:
        command.upgrade(alembic_cfg, "head")
        command.revision(alembic_cfg, autogenerate=True, message="add_probe")
    finally:
        Base.metadata.remove(table)

    versions = list((tmp_path / "alembic" / "versions").glob("*add_probe.py"))
    assert len(versions) == 1, "autogenerate must write exactly one reviewable file"
    content = versions[0].read_text(encoding="utf-8")
    assert "op.create_table" in content
    assert "probe" in content


def test_migration_conflict_exits_nonzero_with_revision_id(alembic_cfg, tmp_path):
    """A broken revision chain -> non-zero CLI exit naming the conflicting id."""
    (tmp_path / "alembic" / "versions" / "0002_conflict.py").write_text(
        '"""conflict"""\n'
        'revision = "bbbb_conflict"\n'
        'down_revision = "aaaa_missing_conflict"\n'
        "branch_labels = None\n"
        "depends_on = None\n\n"
        "def upgrade() -> None:\n"
        "    pass\n\n"
        "def downgrade() -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )

    ini = tmp_path / "alembic.ini"
    ini.write_text(
        "[alembic]\n"
        f"script_location = {tmp_path / 'alembic'}\n"
        f"sqlalchemy.url = sqlite:///{tmp_path / 'test.db'}\n"
        "\n"
        "[loggers]\nkeys = root\n\n"
        "[handlers]\nkeys = console\n\n"
        "[formatters]\nkeys = generic\n\n"
        "[logger_root]\nlevel = WARN\nhandlers = console\nqualname =\n\n"
        "[handler_console]\nclass = StreamHandler\nargs = (sys.stderr,)\n"
        "level = NOTSET\nformatter = generic\n\n"
        "[formatter_generic]\nformat = %(levelname)s %(message)s\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "aaaa_missing_conflict" in combined_output


def test_missing_database_url_is_a_named_error(alembic_cfg, monkeypatch):
    """No DATABASE_URL and no ini URL -> clear named error, not a stack trace."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    alembic_cfg.set_main_option("sqlalchemy.url", "")

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        command.upgrade(alembic_cfg, "head")
