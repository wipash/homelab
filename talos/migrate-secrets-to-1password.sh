#!/usr/bin/env bash
# Migrate Talos secrets from SOPS-encrypted talsecret.sops.yaml to 1Password.
#
# Prerequisites:
#   - sops configured with the correct age key
#   - op CLI authenticated (eval $(op signin))
#   - yq installed
#
# Usage: ./migrate-secrets-to-1password.sh [--dry-run]

set -euo pipefail

SOPS_FILE="kubernetes/bootstrap/talos/talsecret.sops.yaml"
VAULT="Homelab"
ITEM="talos"

if [[ ! -f "$SOPS_FILE" ]]; then
    echo "ERROR: $SOPS_FILE not found. Run from repo root." >&2
    exit 1
fi

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE ==="
fi

echo "Decrypting $SOPS_FILE..."
DECRYPTED=$(sops -d "$SOPS_FILE")

# Extract each field
declare -A FIELDS
FIELDS[MACHINE_CA_CRT]=$(echo "$DECRYPTED" | yq -e '.certs.os.crt')
FIELDS[MACHINE_CA_KEY]=$(echo "$DECRYPTED" | yq -e '.certs.os.key')
FIELDS[MACHINE_TOKEN]=$(echo "$DECRYPTED" | yq -e '.trustdinfo.token')
FIELDS[CLUSTER_ID]=$(echo "$DECRYPTED" | yq -e '.cluster.id')
FIELDS[CLUSTER_SECRET]=$(echo "$DECRYPTED" | yq -e '.cluster.secret')
FIELDS[CLUSTER_TOKEN]=$(echo "$DECRYPTED" | yq -e '.secrets.bootstraptoken')
FIELDS[CLUSTER_CA_CRT]=$(echo "$DECRYPTED" | yq -e '.certs.k8s.crt')
FIELDS[CLUSTER_CA_KEY]=$(echo "$DECRYPTED" | yq -e '.certs.k8s.key')
FIELDS[CLUSTER_AGGREGATORCA_CRT]=$(echo "$DECRYPTED" | yq -e '.certs.k8saggregator.crt')
FIELDS[CLUSTER_AGGREGATORCA_KEY]=$(echo "$DECRYPTED" | yq -e '.certs.k8saggregator.key')
FIELDS[CLUSTER_SERVICEACCOUNT_KEY]=$(echo "$DECRYPTED" | yq -e '.certs.k8sserviceaccount.key')
FIELDS[CLUSTER_ETCD_CA_CRT]=$(echo "$DECRYPTED" | yq -e '.certs.etcd.crt')
FIELDS[CLUSTER_ETCD_CA_KEY]=$(echo "$DECRYPTED" | yq -e '.certs.etcd.key')
FIELDS[CLUSTER_AESCBCENCRYPTIONSECRET]=$(echo "$DECRYPTED" | yq -e '.secrets.aescbcencryptionsecret')

echo ""
echo "Extracted ${#FIELDS[@]} fields:"
for key in $(echo "${!FIELDS[@]}" | tr ' ' '\n' | sort); do
    val="${FIELDS[$key]}"
    preview="${val:0:20}..."
    echo "  $key = $preview (${#val} chars)"
done

if $DRY_RUN; then
    echo ""
    echo "Would create 1Password item '$ITEM' in vault '$VAULT' with the above fields."
    echo "Run without --dry-run to execute."
    exit 0
fi

echo ""
echo "Creating 1Password item '$ITEM' in vault '$VAULT'..."

# Build the op item create command with all fields
FIELD_ARGS=()
for key in $(echo "${!FIELDS[@]}" | tr ' ' '\n' | sort); do
    FIELD_ARGS+=("${key}[password]=${FIELDS[$key]}")
done

op item create \
    --vault "$VAULT" \
    --category "Secure Note" \
    --title "$ITEM" \
    "${FIELD_ARGS[@]}"

echo ""
echo "Done! Verify with:"
echo "  op read 'op://Homelab/talos/MACHINE_TOKEN'"
