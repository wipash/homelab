#!/usr/bin/env bash
#
# migrate-helmrelease.sh
#
# Helper script for migrating HelmReleases from app-template 3.x to 4.x
# Handles the immutable label change by deleting workloads before reconciliation
#
# Usage:
#   ./migrate-helmrelease.sh <app-name> [namespace]
#   ./migrate-helmrelease.sh --batch <file-with-app-names>
#   ./migrate-helmrelease.sh --list-pending
#
# Examples:
#   ./migrate-helmrelease.sh radarr
#   ./migrate-helmrelease.sh radarr default
#   ./migrate-helmrelease.sh --batch apps-to-migrate.txt
#   ./migrate-helmrelease.sh --list-pending
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default namespace
DEFAULT_NAMESPACE="default"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get the workload type and name for a HelmRelease
get_workload_info() {
    local app="$1"
    local namespace="$2"

    # Check for Deployment
    if kubectl get deployment -n "$namespace" "$app" &>/dev/null; then
        echo "deployment $app"
        return
    fi

    # Check for StatefulSet
    if kubectl get statefulset -n "$namespace" "$app" &>/dev/null; then
        echo "statefulset $app"
        return
    fi

    # Check for DaemonSet
    if kubectl get daemonset -n "$namespace" "$app" &>/dev/null; then
        echo "daemonset $app"
        return
    fi

    # Check for CronJob
    if kubectl get cronjob -n "$namespace" "$app" &>/dev/null; then
        echo "cronjob $app"
        return
    fi

    # Try to find by label selector (for apps where workload name differs)
    local deployment
    deployment=$(kubectl get deployment -n "$namespace" -l "app.kubernetes.io/name=$app" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [[ -n "$deployment" ]]; then
        echo "deployment $deployment"
        return
    fi

    local statefulset
    statefulset=$(kubectl get statefulset -n "$namespace" -l "app.kubernetes.io/name=$app" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [[ -n "$statefulset" ]]; then
        echo "statefulset $statefulset"
        return
    fi

    echo "unknown unknown"
}

# Check if HelmRelease exists
helmrelease_exists() {
    local app="$1"
    local namespace="$2"
    kubectl get helmrelease -n "$namespace" "$app" &>/dev/null
}

# Check if workload already has the new label (already migrated)
workload_needs_migration() {
    local app="$1"
    local namespace="$2"

    local workload_info
    workload_info=$(get_workload_info "$app" "$namespace")
    local workload_type workload_name
    workload_type=$(echo "$workload_info" | cut -d' ' -f1)
    workload_name=$(echo "$workload_info" | cut -d' ' -f2)

    if [[ "$workload_type" == "unknown" ]]; then
        # No workload found - needs migration (will be created fresh)
        return 0
    fi

    # Check if workload has the OLD label (app.kubernetes.io/component)
    local old_label
    old_label=$(kubectl get "$workload_type" -n "$namespace" "$workload_name" -o jsonpath='{.metadata.labels.app\.kubernetes\.io/component}' 2>/dev/null || echo "")

    if [[ -n "$old_label" ]]; then
        # Has old label - needs migration
        return 0
    fi

    # Check if workload has the NEW label (app.kubernetes.io/controller)
    local new_label
    new_label=$(kubectl get "$workload_type" -n "$namespace" "$workload_name" -o jsonpath='{.metadata.labels.app\.kubernetes\.io/controller}' 2>/dev/null || echo "")

    if [[ -n "$new_label" ]]; then
        # Has new label - already migrated
        return 1
    fi

    # Neither label found - assume needs migration
    return 0
}

# Get current chart version
get_chart_version() {
    local app="$1"
    local namespace="$2"

    # Check if using chartRef (4.x style)
    local chart_ref
    chart_ref=$(kubectl get helmrelease -n "$namespace" "$app" -o jsonpath='{.spec.chartRef.name}' 2>/dev/null || echo "")
    if [[ -n "$chart_ref" ]]; then
        # Get version from OCIRepository
        local oci_tag
        oci_tag=$(kubectl get ocirepository -n "$namespace" "$chart_ref" -o jsonpath='{.spec.ref.tag}' 2>/dev/null || echo "unknown")
        echo "$oci_tag (OCIRepository)"
        return
    fi

    # Otherwise get from chart spec (3.x style)
    local version
    version=$(kubectl get helmrelease -n "$namespace" "$app" -o jsonpath='{.spec.chart.spec.version}' 2>/dev/null || echo "unknown")
    echo "$version (HelmRepository)"
}

# Migrate a single app
migrate_app() {
    local app="$1"
    local namespace="${2:-$DEFAULT_NAMESPACE}"

    echo ""
    log_info "=========================================="
    log_info "Migrating: $app (namespace: $namespace)"
    log_info "=========================================="

    # Check if HelmRelease exists
    if ! helmrelease_exists "$app" "$namespace"; then
        log_error "HelmRelease '$app' not found in namespace '$namespace'"
        return 1
    fi

    # Check if workload needs migration
    if ! workload_needs_migration "$app" "$namespace"; then
        log_warn "Workload '$app' already has new labels - skipping"
        return 0
    fi

    local version
    version=$(get_chart_version "$app" "$namespace")
    log_info "Current chart version: $version"

    # Get workload info
    local workload_info
    workload_info=$(get_workload_info "$app" "$namespace")
    local workload_type workload_name
    workload_type=$(echo "$workload_info" | cut -d' ' -f1)
    workload_name=$(echo "$workload_info" | cut -d' ' -f2)

    if [[ "$workload_type" == "unknown" ]]; then
        log_warn "Could not find workload for '$app' - it may be a CronJob or not yet deployed"
        log_info "Proceeding anyway..."
    else
        log_info "Found workload: $workload_type/$workload_name"
    fi

    # Step 1: Suspend HelmRelease
    log_info "Step 1: Suspending HelmRelease..."
    if ! flux suspend helmrelease -n "$namespace" "$app"; then
        log_error "Failed to suspend HelmRelease"
        return 1
    fi
    log_success "HelmRelease suspended"

    # Step 2: Delete the workload (if found)
    if [[ "$workload_type" != "unknown" ]]; then
        log_info "Step 2: Deleting $workload_type/$workload_name..."
        if ! kubectl delete "$workload_type" -n "$namespace" "$workload_name" --ignore-not-found; then
            log_error "Failed to delete workload"
            # Resume HelmRelease before exiting
            flux resume helmrelease -n "$namespace" "$app" &>/dev/null || true
            return 1
        fi
        log_success "Workload deleted"
    else
        log_info "Step 2: No workload to delete, skipping..."
    fi

    # Step 3: Resume HelmRelease (this triggers reconciliation)
    log_info "Step 3: Resuming HelmRelease..."
    if ! flux resume helmrelease -n "$namespace" "$app"; then
        log_error "Failed to resume HelmRelease"
        return 1
    fi
    log_success "HelmRelease resumed"

    echo ""
    log_success "Migration complete for '$app'"
    log_info "Monitor with: flux get helmrelease -n $namespace $app"
    log_info "Or watch: kubectl get pods -n $namespace -l app.kubernetes.io/name=$app -w"

    return 0
}

# List HelmReleases that haven't been migrated yet
list_pending() {
    log_info "Scanning for HelmReleases not yet migrated to OCIRepository..."
    echo ""

    printf "%-30s %-15s %-20s %s\n" "NAME" "NAMESPACE" "VERSION" "STATUS"
    printf "%-30s %-15s %-20s %s\n" "----" "---------" "-------" "------"

    # Get all HelmReleases across all namespaces
    while IFS= read -r line; do
        local namespace name
        namespace=$(echo "$line" | awk '{print $1}')
        name=$(echo "$line" | awk '{print $2}')

        # Skip if not app-template
        local chart
        chart=$(kubectl get helmrelease -n "$namespace" "$name" -o jsonpath='{.spec.chart.spec.chart}' 2>/dev/null || echo "")
        if [[ "$chart" != "app-template" ]]; then
            # Check if it's using chartRef pointing to app-template
            local chart_ref
            chart_ref=$(kubectl get helmrelease -n "$namespace" "$name" -o jsonpath='{.spec.chartRef.name}' 2>/dev/null || echo "")
            if [[ -z "$chart_ref" ]]; then
                continue
            fi
            # Check if the OCIRepository is for app-template
            local oci_url
            oci_url=$(kubectl get ocirepository -n "$namespace" "$chart_ref" -o jsonpath='{.spec.url}' 2>/dev/null || echo "")
            if [[ "$oci_url" != *"app-template"* ]]; then
                continue
            fi
        fi

        local version status
        version=$(get_chart_version "$name" "$namespace")

        if workload_needs_migration "$name" "$namespace"; then
            status="PENDING"
        else
            status="migrated"
        fi

        printf "%-30s %-15s %-20s %s\n" "$name" "$namespace" "$version" "$status"

    done < <(kubectl get helmrelease -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name' --no-headers 2>/dev/null)

    echo ""
}

# Process a batch file
process_batch() {
    local batch_file="$1"

    if [[ ! -f "$batch_file" ]]; then
        log_error "Batch file not found: $batch_file"
        exit 1
    fi

    log_info "Processing batch file: $batch_file"

    local success_count=0
    local fail_count=0
    local skip_count=0

    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

        # Parse line: "app namespace" or just "app"
        local app namespace
        app=$(echo "$line" | awk '{print $1}')
        namespace=$(echo "$line" | awk '{print $2}')
        namespace="${namespace:-$DEFAULT_NAMESPACE}"

        if migrate_app "$app" "$namespace"; then
            ((success_count++))
        else
            ((fail_count++))
        fi

        # Small delay between apps
        sleep 2

    done < "$batch_file"

    echo ""
    log_info "=========================================="
    log_info "Batch complete!"
    log_info "  Success: $success_count"
    log_info "  Failed:  $fail_count"
    log_info "=========================================="
}

# Migrate all failing HelmReleases (auto-detect) - batched for speed
migrate_failing() {
    log_info "Scanning for failing HelmReleases that need migration..."
    echo ""

    declare -a apps_to_migrate=()
    declare -a workloads_to_delete=()

    # Find HelmReleases that are failing with upgrade retries exhausted
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue

        local namespace name
        namespace=$(echo "$line" | awk '{print $1}')
        name=$(echo "$line" | awk '{print $2}')

        # Check if this app needs migration (has old label)
        if workload_needs_migration "$name" "$namespace"; then
            apps_to_migrate+=("$namespace:$name")

            # Get workload info
            local workload_info
            workload_info=$(get_workload_info "$name" "$namespace")
            local workload_type workload_name
            workload_type=$(echo "$workload_info" | cut -d' ' -f1)
            workload_name=$(echo "$workload_info" | cut -d' ' -f2)

            if [[ "$workload_type" != "unknown" ]]; then
                workloads_to_delete+=("$namespace:$workload_type:$workload_name")
            fi
        else
            log_info "Skipping $name - already has new labels"
        fi

    done < <(flux get helmrelease -A 2>/dev/null | grep -E "(upgrade retries exhausted|install retries exhausted|HelmChart .* is not ready|field is immutable|Helm rollback)" | awk '{print $1, $2}')

    if [[ ${#apps_to_migrate[@]} -eq 0 ]]; then
        log_info "No failing HelmReleases found that need migration"
        return 0
    fi

    log_info "Found ${#apps_to_migrate[@]} apps to migrate"
    echo ""

    # Step 1: Suspend all HelmReleases
    log_info "Step 1: Suspending all HelmReleases..."
    for app_ref in "${apps_to_migrate[@]}"; do
        IFS=':' read -r namespace name <<< "$app_ref"
        flux suspend helmrelease -n "$namespace" "$name" &
    done
    wait
    log_success "All HelmReleases suspended"

    # Step 2: Delete all workloads
    log_info "Step 2: Deleting all workloads..."
    for workload_ref in "${workloads_to_delete[@]}"; do
        IFS=':' read -r namespace workload_type workload_name <<< "$workload_ref"
        kubectl delete "$workload_type" -n "$namespace" "$workload_name" --ignore-not-found &
    done
    wait
    log_success "All workloads deleted"

    # Step 3: Resume all HelmReleases (this triggers reconciliation)
    log_info "Step 3: Resuming all HelmReleases..."
    for app_ref in "${apps_to_migrate[@]}"; do
        IFS=':' read -r namespace name <<< "$app_ref"
        flux resume helmrelease -n "$namespace" "$name" &
    done
    wait
    log_success "All HelmReleases resumed"

    echo ""
    log_info "=========================================="
    log_info "Migration complete!"
    log_info "  Migrated: ${#apps_to_migrate[@]} apps"
    log_info "=========================================="
    log_info "Monitor with: flux get helmrelease -A"
}

# Delete workload and trigger recreation (for already-migrated apps)
delete_workload_only() {
    local app="$1"
    local namespace="${2:-$DEFAULT_NAMESPACE}"

    log_info "Recreating workload for: $app (namespace: $namespace)"

    local workload_info
    workload_info=$(get_workload_info "$app" "$namespace")
    local workload_type workload_name
    workload_type=$(echo "$workload_info" | cut -d' ' -f1)
    workload_name=$(echo "$workload_info" | cut -d' ' -f2)

    if [[ "$workload_type" == "unknown" ]]; then
        log_warn "Could not find workload for '$app'"
        return 1
    fi

    # Suspend HelmRelease first
    log_info "Suspending HelmRelease..."
    flux suspend helmrelease -n "$namespace" "$app" || true

    # Delete the workload
    log_info "Deleting $workload_type/$workload_name..."
    kubectl delete "$workload_type" -n "$namespace" "$workload_name" --ignore-not-found
    log_success "Deleted $workload_type/$workload_name"

    # Resume HelmRelease to trigger recreation
    log_info "Resuming HelmRelease..."
    flux resume helmrelease -n "$namespace" "$app"
    log_success "HelmRelease resumed - workload will be recreated"
}

# Show usage
usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS] <app-name> [namespace]

Migrate HelmReleases from app-template 3.x to 4.x by handling the immutable
label change (app.kubernetes.io/component -> app.kubernetes.io/controller).

Options:
    -h, --help          Show this help message
    -l, --list-pending  List all app-template HelmReleases and their migration status
    -f, --failing       Auto-detect and migrate all failing HelmReleases
    -b, --batch FILE    Process multiple apps from a file (one per line: "app namespace")
    -d, --delete-only   Recreate workload via suspend/delete/resume (for already-migrated apps)

Examples:
    # Migrate a single app
    $(basename "$0") radarr
    $(basename "$0") radarr default

    # Auto-migrate all failing HelmReleases
    $(basename "$0") --failing

    # List pending migrations
    $(basename "$0") --list-pending

    # Batch migrate from file
    $(basename "$0") --batch apps.txt

    # Recreate workload (for already-migrated apps)
    $(basename "$0") --delete-only radarr

Batch file format (apps.txt):
    # Comments start with #
    radarr default
    sonarr default
    plex default
    authelia default

Workflow:
    1. Update your HelmRelease YAML files (chart.spec -> chartRef, add ocirepository.yaml)
    2. Commit and push changes
    3. Run this script to delete workloads and trigger reconciliation
    4. Monitor: flux get helmrelease -A

EOF
}

# Main
main() {
    if [[ $# -eq 0 ]]; then
        usage
        exit 1
    fi

    case "${1:-}" in
        -h|--help)
            usage
            exit 0
            ;;
        -l|--list-pending)
            list_pending
            exit 0
            ;;
        -f|--failing)
            migrate_failing
            exit 0
            ;;
        -b|--batch)
            if [[ -z "${2:-}" ]]; then
                log_error "Batch file required"
                usage
                exit 1
            fi
            process_batch "$2"
            exit 0
            ;;
        -d|--delete-only)
            if [[ -z "${2:-}" ]]; then
                log_error "App name required"
                usage
                exit 1
            fi
            delete_workload_only "$2" "${3:-$DEFAULT_NAMESPACE}"
            exit 0
            ;;
        -*)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
        *)
            migrate_app "$1" "${2:-$DEFAULT_NAMESPACE}"
            exit $?
            ;;
    esac
}

main "$@"
