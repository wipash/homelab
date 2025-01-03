#!/bin/bash

# Apply the job
kubectl apply -f cleanup-job.yaml

echo "Waiting for pods to be ready..."
kubectl wait --for=condition=Ready pods -l job-name=cleanup-images --timeout=60s

# Show logs
kubectl logs -l job-name=cleanup-images --tail=-1 -f &
LOGS_PID=$!

# Wait for job to complete
kubectl wait --for=condition=Complete job/cleanup-images --timeout=300s

# Kill the logs process
kill $LOGS_PID

# Clean up the job
kubectl delete -f cleanup-job.yaml

echo "Cleanup complete!"
