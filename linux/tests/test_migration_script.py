import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "linux" / "deploy" / "migrate-snifferops-to-ethrox-detect.sh"


def test_migration_script_has_valid_bash_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_migration_script_documents_required_safety_steps():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "migration-backups" in text
    assert "systemctl --user stop" in text
    assert "ethrox-detect.service" in text
    assert "curl -fsS" in text
    assert "Rollback:" in text
