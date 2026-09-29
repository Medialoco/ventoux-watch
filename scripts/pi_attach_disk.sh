#!/usr/bin/env bash
# Bascule les données du veilleur sur un disque externe.
#
# Le disque est EFFACÉ. Le script exige donc qu'on lui nomme le périphérique et
# qu'on confirme, et il refuse tout ce qui ressemble à la carte SD du système.
#
#   ssh ventoux 'bash -s' < scripts/pi_attach_disk.sh -- /dev/sda EFFACER
set -euo pipefail

DISQUE="${1:-}"
AVEU="${2:-}"
RACINE="${RACINE:-/opt/ventoux-watch}"
POINT="/srv/ventoux"

dire() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

if [ -z "$DISQUE" ]; then
    dire "Disques vus par le système"
    lsblk -o NAME,SIZE,TRAN,MODEL,MOUNTPOINT
    echo
    echo "Relancer avec le périphérique et le mot EFFACER, par exemple :"
    echo "  bash pi_attach_disk.sh /dev/sda EFFACER"
    exit 2
fi

case "$DISQUE" in
    /dev/mmcblk*|/dev/nvme0n1p*) echo "Refus : $DISQUE est le support du système." >&2; exit 1;;
esac
[ -b "$DISQUE" ] || { echo "Refus : $DISQUE n'est pas un disque." >&2; exit 1; }
if lsblk -no MOUNTPOINT "$DISQUE" | grep -qx "/"; then
    echo "Refus : $DISQUE porte la racine du système." >&2; exit 1
fi
[ "$AVEU" = "EFFACER" ] || { echo "Refus : confirmation manquante." >&2; exit 1; }

dire "Liaison"
case "$DISQUE" in
    /dev/nvme*)
        # Branché sur le connecteur PCIe du Pi 5, par une nappe et une carte
        # fille : il n'y a pas de port M.2 sur la carte elle-même.
        echo "NVMe sur PCIe. UASP ne s'applique pas."
        sudo nvme list 2>/dev/null | tail -2 || lsblk -o NAME,SIZE,MODEL "$DISQUE"
        ;;
    *)
        # UASP fait la différence entre un disque utilisable et un disque
        # poussif. Le pilote doit être « uas », pas « usb-storage ».
        if lsusb -t | grep -q "Driver=uas"; then
            echo "UASP actif."
        else
            echo "ATTENTION : le disque est en usb-storage, sans UASP. Débit divisé"
            echo "par trois environ, et charge processeur plus élevée."
        fi
        ;;
esac

dire "Partition et système de fichiers"
sudo systemctl stop ventoux-watch 2>/dev/null || true
sudo umount "${DISQUE}"* 2>/dev/null || true
sudo wipefs -a "$DISQUE"
sudo sgdisk -Z -n 1:0:0 -t 1:8300 -c 1:ventoux "$DISQUE"
sudo partprobe "$DISQUE"; sleep 2
PART="$(lsblk -nro NAME "$DISQUE" | sed -n '2p')"
PART="/dev/$PART"
# Pas de réserve pour root : ce disque ne porte pas de système.
sudo mkfs.ext4 -q -m 0 -L ventoux "$PART"

dire "Déménagement des données"
# Le disque est monté SUR data/, et non relié par un lien symbolique : data/
# est suivi par git, et un lien ferait voir à git la disparition des deux mille
# fichiers d'un coup. Un point de montage, lui, est invisible pour git.
sudo mkdir -p "$POINT"
sudo mount "$PART" "$POINT"
sudo chown "$USER:$USER" "$POINT"
rsync -a "$RACINE/data/" "$POINT/"
sudo umount "$POINT"
# Le dossier d'origine est vidé : ce qu'il contiendrait encore serait masqué
# par le montage et occuperait la carte SD pour rien.
rm -rf "${RACINE:?}/data"
mkdir -p "$RACINE/data"

dire "Montage définitif"
UUID="$(sudo blkid -s UUID -o value "$PART")"
sudo sed -i '\#ventoux-watch/data#d' /etc/fstab
# nofail : un disque débranché ne doit pas empêcher le Pi de démarrer, sinon on
# perd la machine et la webcam avec.
echo "UUID=$UUID $RACINE/data ext4 defaults,noatime,nofail,x-systemd.device-timeout=10 0 2" | sudo tee -a /etc/fstab >/dev/null
sudo systemctl daemon-reload
sudo mount "$RACINE/data"
sudo chown "$USER:$USER" "$RACINE/data"

dire "TRIM"
# Sans TRIM, un SSD ralentit et s'use plus vite à mesure qu'il se remplit.
sudo systemctl enable --now fstrim.timer >/dev/null
sudo fstrim -v "$RACINE/data" || echo "TRIM non supporté par ce boîtier."

dire "État"
df -h "$RACINE/data" | tail -1
git -C "$RACINE" status --porcelain -- data | head -3
echo "Si git ne signale rien ci-dessus, le déménagement est transparent."
echo "Redémarrer le veilleur : sudo systemctl start ventoux-watch"
