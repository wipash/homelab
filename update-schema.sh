#!/bin/bash

# Script to dynamically find and update the yaml-language-server schema in all app-template helm chart files

# Target schema
NEW_SCHEMA="# yaml-language-server: \$schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json"

echo "Finding all app-template helm chart files..."

# Find all YAML files that contain "chart: app-template" and store them in an array
mapfile -t FILES < <(grep -r --include="*.yaml" --include="*.yml" "chart: app-template" /home/sean/homelab --files-with-matches)

echo "Found ${#FILES[@]} files to update"

# Process each file
for file in "${FILES[@]}"; do
  echo "Processing: $file"

  # Create a temporary file
  temp_file=$(mktemp)

  # Check if file starts with "---"
  if head -n 1 "$file" | grep -q "^---"; then
    # If file starts with "---", insert schema after it
    if grep -q "yaml-language-server:" "$file"; then
      # Replace existing schema line
      awk 'NR==1{print} NR==2 && /yaml-language-server/{print "'"$NEW_SCHEMA"'"} NR==2 && !/yaml-language-server/{print; print "'"$NEW_SCHEMA"'"} NR>2{print}' "$file" > "$temp_file"
      echo "  Updated schema with triple dash header"
    else
      # Add schema after "---"
      awk 'NR==1{print; print "'"$NEW_SCHEMA"'"} NR>1{print}' "$file" > "$temp_file"
      echo "  Added schema with triple dash header"
    fi
  else
    # Handle files without "---" at the start
    if grep -q "yaml-language-server:" "$file"; then
      # Replace existing schema
      awk '/yaml-language-server/{if (NR==1) {print "'"$NEW_SCHEMA"'"} else {print}} !/yaml-language-server/{print}' "$file" > "$temp_file"
      echo "  Updated schema"
    else
      # Add schema at beginning
      echo -e "$NEW_SCHEMA\n$(cat "$file")" > "$temp_file"
      echo "  Added schema"
    fi
  fi

  # Replace original file with temporary file
  mv "$temp_file" "$file"
done

echo "Schema update complete!"
