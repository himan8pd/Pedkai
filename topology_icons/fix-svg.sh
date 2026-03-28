#!/bin/bash

# Folder containing SVGs (default = current directory)
DIR="${1:-.}"

for file in "$DIR"/*.svg; do
  [ -e "$file" ] || continue

  # Skip if xmlns already exists
  if grep -q 'xmlns="http://www.w3.org/2000/svg"' "$file"; then
    echo "Skipping (already has xmlns): $file"
    continue
  fi

  echo "Fixing: $file"

  # Insert xmlns into the opening <svg ...> tag
  sed -i '' 's|<svg|<svg xmlns="http://www.w3.org/2000/svg"|' "$file"
done

echo "Done."