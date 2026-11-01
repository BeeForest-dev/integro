"""Tests for C05 db.migrations — Alembic wired to the same metadata.

Behavioural tests run Alembic against a temporary copy of the migration
tree and a file-based SQLite database, so no PostgreSQL server is needed.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, Table, create_engine, text

from alembic import command
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


def _write_revision(path: Path, revision: str, down_revision: str) -> None:
    """Write a minimal no-op revision file."""
    path.write_text(
        f'"""{revision}"""\n'
        f'revision = "{revision}"\n'
        f'down_revision = "{down_revision}"\n'
        "branch_labels = None\n"
        "depends_on = None\n\n"
        "def upgrade() -> None:\n"
        "    pass\n\n"
        "def downgrade() -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )


def _write_ini(tmp_path: Path) -> Path:
    """Write an alembic.ini with the logging sections fileConfig requires."""
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
    return ini


def _run_alembic_cli(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run `alembic upgrade head` as a real CLI subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_write_ini(tmp_path)), "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(BACKEND_DIR),
    )


def test_upgrade_head_produces_schema(alembic_cfg):
    """`alembic upgrade head` stamps the database with the head revision."""
    command.upgrade(alembic_cfg, "head")

    head = ScriptDirectory.from_config(alembic_cfg).get_current_head()
    engine = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()

    assert version == head


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


def test_duplicate_revision_id_exits_nonzero_with_revision_id(alembic_cfg, tmp_path):
    """Two revisions sharing one id -> non-zero exit naming the conflicting id."""
    _write_revision(tmp_path / "alembic" / "versions" / "0002_dup_a.py", "dup_conflict", "0001_baseline")
    _write_revision(tmp_path / "alembic" / "versions" / "0003_dup_b.py", "dup_conflict", "0001_baseline")

    result = _run_alembic_cli(tmp_path)

    combined_output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "dup_conflict" in combined_output


def test_missing_parent_exits_nonzero_with_revision_id(alembic_cfg, tmp_path):
    """A revision pointing at a missing parent -> non-zero exit naming the id."""
    _write_revision(
        tmp_path / "alembic" / "versions" / "0002_conflict.py",
        "bbbb_conflict",
        "aaaa_missing_conflict",
    )

    result = _run_alembic_cli(tmp_path)

    combined_output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "aaaa_missing_conflict" in combined_output


def test_missing_database_url_is_a_named_error(alembic_cfg, monkeypatch):
    """No DATABASE_URL and no ini URL -> clear named error, not a stack trace."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    alembic_cfg.set_main_option("sqlalchemy.url", "")

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        command.upgrade(alembic_cfg, "head")
