#!/usr/bin/env bash
# Start Neo4j from the tarball install (run hpc/install_neo4j.sh first).
# Runs in the foreground — keep this terminal open while working.
# Ctrl-C to stop Neo4j cleanly.
#
# Usage:
#   bash hpc/start_neo4j.sh

set -euo pipefail

NEO4J_HOME="${HOME}/neo4j"

if [[ ! -d "${NEO4J_HOME}" ]]; then
  echo "ERROR: ${NEO4J_HOME} not found. Run hpc/install_neo4j.sh first."
  exit 1
fi

if ! command -v java &>/dev/null; then
  echo "ERROR: java not found. Load the module first:"
  echo "  module load java/17"
  exit 1
fi

echo "Starting Neo4j..."
echo "  Bolt   : bolt://localhost:7687"
echo "  Browser: http://localhost:7474"
echo "  Ctrl-C to stop."
echo ""

exec "${NEO4J_HOME}/bin/neo4j" console
