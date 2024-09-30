#!/usr/bin/env bash

JOB=$1
NAMESPACE="${2:-default}"

[[ -z "${JOB}" ]] && echo "Job name not specified" && exit 1
echo "Waiting for job ${JOB} to start or is already complete"
while true; do
    STATUS="$(kubectl --namespace "${NAMESPACE}" get pod --selector="job-name=${JOB}" --output="jsonpath={.items[*].status.phase}")"
    echo "Job status: ${STATUS}"
    if [ "${STATUS}" == "Pending" ] || [ "${STATUS}" == "Succeeded" ]; then
        break
    fi
    sleep 1
done
