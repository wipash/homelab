#!/bin/sh
# Bypass flock for read-only session listing: synology-csi treats any non-zero
# exit from `iscsiadm -m session` as "no active sessions", which would skip logout.
if [ "$1" = "-m" ] && [ "$2" = "session" ] && [ "$#" -eq 2 ]; then
  exec /usr/sbin/chroot /host /usr/local/sbin/iscsiadm "$@"
fi
# Prune stale open-iscsi DB entries during SendTargets discovery. synology-csi
# passes only --op new and never deletes node records on logout, so hourly
# VolSync ephemeral targets otherwise accumulate into tens of thousands of entries.
if [ "$1" = "-m" ] && [ "$2" = "discoverydb" ]; then
  case " $* " in
    *" --discover "*)
      case " $* " in
        *" --op delete "*) ;;
        *) set -- "$@" --op delete ;;
      esac
      ;;
  esac
fi
# Serialise discovery and mutating iscsiadm calls per node so concurrent mounts
# do not trigger Synology LIO discovery session reinstatement or DB lock pileups.
# -o closes the lock FD before exec, -w 90 stays under kubelet's 2m CSI deadline,
# and -E 75 avoids colliding with open-iscsi exit codes (0..32).
exec /usr/bin/flock -o -w 90 -E 75 /tmp/iscsiadm.lock /usr/sbin/chroot /host /usr/local/sbin/iscsiadm "$@"
