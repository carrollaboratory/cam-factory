pg_container := env_var_or_default("CAM_PG_CONTAINER", "cam-testdata-pg")
# Pinned by digest: SQL dump headers record the server/package version, so a
# different image would change output/tiny/sql. Keep .github/workflows/check.yml in step.
pg_image := env_var_or_default("CAM_PG_IMAGE", "postgres:18.6@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722")
pg_port := env_var_or_default("CAM_PG_PORT", "5432")
pg_volume := pg_container + "-data"
pg_dbs := "cam_testdata_tiny cam_testdata_small cam_testdata_portal cam_testdata_test"

# Install dependencies and start Postgres
setup: && pg-up
  uv sync

build profile:
  uv run cam-testdata build --profile {{profile}}

tiny: (build "tiny")

small: (build "small")

portal: (build "portal")

test *args="":
  uv run pytest {{args}}

lint:
  uv run ruff check
  uv run ruff format --check
  uv run mypy

# Reproducible release archive of output/<profile> in dist/ (you upload it)
dist profile:
  uv run cam-testdata dist --profile {{profile}}

# Round-trip each SQL dump through a scratch DB and byte-compare its CSVs
verify-sql profile="tiny":
  uv run cam-testdata verify-sql --profile {{profile}}

# Lint + test + build tiny; fail if output/tiny or its scenario doc changed (untracked files count)
check: lint test tiny
  #!/usr/bin/env bash
  set -euo pipefail
  changes="$(git status --porcelain -- output/tiny docs/SCENARIO_TINY.md)"
  if [ -n "$changes" ]; then
    echo "output/tiny changed; explain it in your summary (or commit it):"
    echo "$changes" | head -20
    exit 1
  fi

# Update the common-access-model monolith YAML file
update-cam:
  uv run update-cam -d data

# Start the local Postgres container (trust auth, localhost only) and create the profile DBs
pg-up:
  #!/usr/bin/env bash
  set -euo pipefail
  if [ -z "$(docker ps -aq -f name=^{{pg_container}}$)" ]; then
    docker run -d --name {{pg_container}} \
      -e POSTGRES_HOST_AUTH_METHOD=trust \
      -p 127.0.0.1:{{pg_port}}:5432 \
      -v {{pg_volume}}:/var/lib/postgresql \
      {{pg_image}} >/dev/null
  elif [ -z "$(docker ps -q -f name=^{{pg_container}}$)" ]; then
    docker start {{pg_container}} >/dev/null
  fi
  until docker exec {{pg_container}} pg_isready -h localhost -U postgres -q; do sleep 0.5; done
  for db in {{pg_dbs}}; do
    if [ -z "$(docker exec {{pg_container}} psql -h localhost -U postgres -tAc "select 1 from pg_database where datname = '$db'")" ]; then
      docker exec {{pg_container}} createdb -h localhost -U postgres "$db"
      echo "created $db"
    fi
  done
  echo "ready: postgresql://postgres@localhost:{{pg_port}}/<db>"

# Stop the container; data persists in the volume
pg-down:
  docker stop {{pg_container}}

# Remove the container and its data volume
pg-destroy:
  docker rm -f {{pg_container}}
  docker volume rm {{pg_volume}}

# psql inside the container, e.g. `just psql cam_testdata_tiny`
psql db="cam_testdata_tiny" *args="":
  docker exec -it {{pg_container}} psql -U postgres -d {{db}} {{args}}

# pg_dump inside the container so client and server versions always match
pg-dump db *args="":
  docker exec {{pg_container}} pg_dump -U postgres -d {{db}} {{args}}
