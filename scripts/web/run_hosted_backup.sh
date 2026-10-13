#!/bin/sh
# Prepared for a separately authorized root-owned systemd unit only. No OneBot
# service, credential, cron entry or timer is addressed. No deletion/retention.
set -eu
resume_onejournal=no
if systemctl is-active --quiet onejournal.service; then
    resume_onejournal=yes
    systemctl stop onejournal.service
fi
resume() {
    if [ "$resume_onejournal" = yes ]; then
        systemctl start onejournal.service
    fi
}
trap resume EXIT
image_name="onejournal-$(date -u +%Y%m%dT%H%M%SZ).onj"
runuser -u onejournal -- /opt/onejournal/current/python-env/bin/python \
    /opt/onejournal/current/commands/backup_hosted_store.py create \
    --config /var/lib/onejournal/private/hosted.json \
    --password-file /var/lib/onejournal/private/backup-password.txt \
    --image "/var/lib/onejournal/backups/$image_name"
# Off-server copy and its confirmation are mandatory before backup acceptance.
# The destination is an owner decision, not silently inferred from OneBot.
