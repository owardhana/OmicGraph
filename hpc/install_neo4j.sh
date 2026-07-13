#!/usr/bin/env bash
# Download and configure Neo4j Community + APOC in $HOME.
# No root, no containers, no modules needed beyond Java 17.
#
# Run once on the HPC (login node or compute node — either works):
#   bash hpc/install_neo4j.sh
#
# What it does:
#   1. Downloads neo4j-community tarball into $HOME
#   2. Extracts to $HOME/neo4j
#   3. Downloads APOC plugin JAR
#   4. Writes neo4j.conf settings (data dir, APOC, memory, auth)
#
# After this, start Neo4j with:  bash hpc/start_neo4j.sh

set -euo pipefail

NEO4J_VERSION="${NEO4J_VERSION:-5.26.0}"
APOC_VERSION="${APOC_VERSION:-5.26.1}"
NEO4J_HOME="${HOME}/neo4j"
NEO4J_DATA="${HOME}/neo4j_data"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-changeme}"

# Memory: HPC nodes have large RAM. Override with env vars.
HEAP_MAX="${NEO4J_HEAP_MAX:-8G}"
PAGECACHE="${NEO4J_PAGECACHE:-8G}"

echo "=== OmicGraph Neo4j tarball install ==="
echo "  Version    : ${NEO4J_VERSION}"
echo "  Install dir: ${NEO4J_HOME}"
echo "  Data dir   : ${NEO4J_DATA}"

# ── 1. Java check ───────────────────────────────────────────────────────────
if ! command -v java &>/dev/null; then
  echo ""
  echo "ERROR: java not found."
  echo "Load the Java 17 module first:"
  echo "  module avail java        # list available versions"
  echo "  module load java/17      # adjust to what's available"
  exit 1
fi
JAVA_VER="$(java -version 2>&1 | head -1)"
echo "  Java       : ${JAVA_VER}"

# ── 2. Download tarball ─────────────────────────────────────────────────────
TARBALL="${HOME}/neo4j-community-${NEO4J_VERSION}-unix.tar.gz"
if [[ ! -f "${TARBALL}" ]]; then
  echo ""
  echo "[1/4] Downloading Neo4j ${NEO4J_VERSION}..."
  curl -fL --retry 3 --progress-bar \
    "https://dist.neo4j.org/neo4j-community-${NEO4J_VERSION}-unix.tar.gz" \
    -o "${TARBALL}"
else
  echo ""
  echo "[1/4] Tarball already downloaded — skipping."
fi

# ── 3. Extract ──────────────────────────────────────────────────────────────
if [[ ! -d "${NEO4J_HOME}" ]]; then
  echo "[2/4] Extracting..."
  tar xzf "${TARBALL}" -C "${HOME}"
  # Rename versioned dir to a stable name
  mv "${HOME}/neo4j-community-${NEO4J_VERSION}" "${NEO4J_HOME}"
else
  echo "[2/4] ${NEO4J_HOME} already exists — skipping extract."
fi

# ── 4. APOC plugin ─────────────────────────────────────────────────────────
APOC_JAR="${NEO4J_HOME}/plugins/apoc-${APOC_VERSION}-core.jar"
if [[ ! -f "${APOC_JAR}" ]]; then
  echo "[3/4] Downloading APOC ${APOC_VERSION}..."
  curl -fL --retry 3 --progress-bar \
    "https://github.com/neo4j/apoc/releases/download/${APOC_VERSION}/apoc-${APOC_VERSION}-core.jar" \
    -o "${APOC_JAR}"
else
  echo "[3/4] APOC already present — skipping."
fi

# ── 5. neo4j.conf ───────────────────────────────────────────────────────────
echo "[4/4] Writing neo4j.conf..."
mkdir -p "${NEO4J_DATA}"

CONF="${NEO4J_HOME}/conf/neo4j.conf"

# Remove any existing settings we're about to set so we don't duplicate.
sed -i '/^server\.directories\.data/d'                 "${CONF}" 2>/dev/null || true
sed -i '/^server\.memory\.heap/d'                      "${CONF}" 2>/dev/null || true
sed -i '/^server\.memory\.pagecache/d'                 "${CONF}" 2>/dev/null || true
sed -i '/^dbms\.security\.procedures/d'                "${CONF}" 2>/dev/null || true
sed -i '/^dbms\.security\.auth_enabled/d'              "${CONF}" 2>/dev/null || true
sed -i '/^server\.bolt\.listen_address/d'              "${CONF}" 2>/dev/null || true
sed -i '/^server\.http\.listen_address/d'              "${CONF}" 2>/dev/null || true

cat >> "${CONF}" <<EOF

# ── OmicGraph HPC settings (written by hpc/install_neo4j.sh) ──
server.directories.data=${NEO4J_DATA}
server.memory.heap.max_size=${HEAP_MAX}
server.memory.pagecache.size=${PAGECACHE}
dbms.security.procedures.unrestricted=apoc.*
dbms.security.procedures.allowlist=apoc.*
server.bolt.listen_address=0.0.0.0:7687
server.http.listen_address=0.0.0.0:7474
EOF

# Set initial password (neo4j-admin tool)
echo "  Setting password..."
"${NEO4J_HOME}/bin/neo4j-admin" dbms set-initial-password "${NEO4J_PASSWORD}" 2>/dev/null \
  || echo "  (password already set — skipping)"

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  Neo4j installed at: ${NEO4J_HOME}"
echo "║"
echo "║  Start it:   bash hpc/start_neo4j.sh"
echo "║  Bolt:       bolt://localhost:7687"
echo "║  Browser:    http://localhost:7474"
echo "║  Auth:       neo4j / ${NEO4J_PASSWORD}"
echo "╚════════════════════════════════════════════════════════╝"
