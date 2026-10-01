pg_container := env_var_or_default("CAM_PG_CONTAINER", "cam-testdata-pg")
pg_image := env_var_or_default("CAM_PG_IMAGE", "postgres:18")
pg_port := env_var_or_default("CAM_PG_PORT", "5432")
pg_volume := pg_container + "-data"
pg_dbs := "cam_testdata_tiny cam_testdata_small cam_testdata_portal cam_testdata_test"

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
