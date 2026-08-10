from app.services.mount_ops import _cron_probe_command


def test_cron_probe_keeps_path_globbing_available_for_spool_files() -> None:
    command = _cron_probe_command()

    assert "script=/db/backup/scripts/mount.sh; set -f;" not in command
    assert command.count("set -f; set -- $line; set +f;") == 2
    assert 'for f in "$d"/*;' in command
    assert "/var/spool/cron" in command
