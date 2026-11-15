# Base de Datos II - Trabajo Práctico Obligatorio

## Requisitos

- **Python 3.11 o superior** (el devcontainer usa 3.12).
- **Docker** con Docker Compose v2 (Docker Desktop en macOS/Windows o Docker
  Engine en Linux).
- 4 GB de memoria y 16 GB de disco libres (recomendado para Codespaces).
- Puertos libres: `27017` (MongoDB), `7474` (Neo4j Browser), `7687` (Neo4j Bolt)
  y `7688` (Neo4j Bolt de pruebas).

Dependencias de Python: `pymongo`, `neo4j` y `python-dotenv`; `pytest` para las pruebas. Están declaradas en [`pyproject.toml`](pyproject.toml).

---

## Inicio rápido en GitHub Codespaces

1. Abrir el repositorio en un Codespace.
2. El contenedor instala el paquete con `pip install -e '.[dev]'` y, al iniciar, ejecuta `docker compose up -d` automáticamente (Docker-in-Docker).
3. Esperar a que los servicios estén `healthy`:

    ```bash
    docker compose ps
    ```

4. Cargar los CSV y construir el grafo:

    ```bash
    python -m src.cli seed
    ```

5. Verificar el entorno:

    ```bash
    python -m src.cli wait-for-services
    docker compose --profile test up -d --wait neo4j-test
    NEO4J_TEST_URI='bolt://localhost:7688' \
    NEO4J_TEST_USER='neo4j' \
    NEO4J_TEST_PASSWORD='test_password' \
    pytest
    ```

El devcontainer ya define `MONGO_URI`, `MONGO_DB`, `NEO4J_URI`, `NEO4J_USER` y `NEO4J_PASSWORD`, y reenvía los puertos `27017`, `7474` y `7687`.

---

## Configuración local

```bash
# 1. Crear y activar el entorno virtual
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Instalar el paquete y las dependencias de desarrollo
pip install -e '.[dev]'

# 3. Crear el archivo de configuración
cp .env.example .env
# Si el cliente se ejecuta en el host (fuera de Docker), usar las URIs
# con localhost y directConnection=true de la tabla siguiente.

# 4. Levantar los servicios
docker compose up -d --wait

# 5. Cargar los datos
python -m src.cli seed
```

### URIs según el contexto

| Contexto                                      | `MONGO_URI`                                                       | `NEO4J_URI`             |
| --------------------------------------------- | ----------------------------------------------------------------- | ----------------------- |
| Contenedor / Codespaces (Docker-in-Docker)    | `mongodb://localhost:27017/?directConnection=true&replicaSet=rs0` | `bolt://localhost:7687` |
| Host con Docker Desktop                       | `mongodb://localhost:27017/?directConnection=true&replicaSet=rs0` | `bolt://localhost:7687` |
| Dentro de la red de Compose (otro contenedor) | `mongodb://mongo:27017/?replicaSet=rs0`                           | `bolt://neo4j:7687`     |

Desde el host es necesario `directConnection=true`: el replica set anuncia el host `mongo:27017`, que no resuelve fuera de Docker. Sin ese parámetro, PyMongo falla con `ServerSelectionTimeoutError`.

---

## Variables de entorno

| Variable         | Por defecto (`.env.example`)            | Descripción                      |
| ---------------- | --------------------------------------- | -------------------------------- |
| `MONGO_URI`      | `mongodb://mongo:27017/?replicaSet=rs0` | Cadena de conexión de MongoDB    |
| `MONGO_DB`       | `farmared`                              | Base de datos operativa          |
| `NEO4J_URI`      | `bolt://neo4j:7687`                     | Endpoint Bolt de Neo4j           |
| `NEO4J_USER`     | `neo4j`                                 | Usuario de Neo4j                 |
| `NEO4J_PASSWORD` | `development_password`                  | Contraseña de Neo4j              |
| `DATA_DIR`       | `./data`                                | Directorio de los CSV de entrada |

---

## Levantamiento de Docker

```bash
docker compose up -d --wait		# inicia mongo, mongo-init y neo4j
docker compose ps				# mongo y neo4j deben figurar como healthy
docker compose logs -f mongo	# opcional
docker compose down				# detiene sin borrar datos
```

Servicios:

| Servicio     | Imagen                 | Puertos        | Función                            |
| ------------ | ---------------------- | -------------- | ---------------------------------- |
| `mongo`      | `mongo:7.0`            | `27017`        | MongoDB como replica set `rs0`     |
| `mongo-init` | `mongo:7.0`            | —              | One-shot que inicia el replica set |
| `neo4j`      | `neo4j:5.26-community` | `7474`, `7687` | Proyección de grafos               |
| `neo4j-test` | `neo4j:5.26-community` | `7688` | Neo4j desechable para Q02 (perfil `test`) |

Los datos persisten en los volúmenes `farmared-mongo-data`, `farmared-neo4j-data` y `farmared-neo4j-logs`.

---

## Carga inicial en MongoDB y Neo4j

El flujo completo se ejecuta con un solo comando:

```bash
python -m src.cli seed
# o, usando el script (levanta Docker primero)
./scripts/seed.sh
```

### Comandos individuales

| Comando                               | Acción                                  |
| ------------------------------------- | --------------------------------------- |
| `python -m src.cli show-config`       | Muestra la configuración                |
| `python -m src.cli validate-data`     | Valida y normaliza los CSV              |
| `python -m src.cli load-mongodb`      | Valida y carga MongoDB + índices        |
| `python -m src.cli build-neo4j`       | Reconstruye la proyección desde MongoDB |
| `python -m src.cli wait-for-services` | Verifica conectividad con ambos motores |
| `python -m src.cli seed`              | Ejecuta el flujo completo               |
| `python -m src.cli reset`             | Limpia MongoDB y la proyección de Neo4j |

Los comandos `wait-for-services`, `build-neo4j`, `seed` y `reset` aceptan `--timeout <segundos>` (60 por defecto). El script `scripts/seed.sh` levanta Docker y delega en `seed`.

---

## Pruebas

Comandos útiles:

```bash
# Solo unitarias (no requieren Docker)
pytest -m "not integration"

# Integración desde el host, con servicios levantados
docker compose --profile test up -d --wait neo4j-test
MONGO_URI='mongodb://localhost:27017/?directConnection=true&replicaSet=rs0' \
NEO4J_URI='bolt://localhost:7687' \
NEO4J_TEST_URI='bolt://localhost:7688' \
NEO4J_TEST_USER='neo4j' \
NEO4J_TEST_PASSWORD='test_password' \
pytest
```

### Pruebas Q02 aisladas

El servicio `neo4j-test` no se inicia con los servicios habituales. Estos
comandos levantan y esperan únicamente su contenedor, ejecutan Q02 dos veces y
eliminan solo el contenedor y sus volúmenes desechables:

```bash
docker compose --profile test up -d --wait neo4j-test
NEO4J_TEST_URI='bolt://localhost:7688' \
NEO4J_TEST_USER='neo4j' \
NEO4J_TEST_PASSWORD='test_password' \
pytest tests/test_q02.py
NEO4J_TEST_URI='bolt://localhost:7688' \
NEO4J_TEST_USER='neo4j' \
NEO4J_TEST_PASSWORD='test_password' \
pytest tests/test_q02.py
docker compose --profile test rm --stop --force neo4j-test
docker volume rm farmared-neo4j-test-data farmared-neo4j-test-logs
```

El fixture falla con un mensaje accionable si el servicio no está disponible o
si `NEO4J_TEST_URI` coincide con el endpoint configurado para la aplicación.
Estos comandos no detienen ni recrean los servicios o volúmenes de la
aplicación.

---

## Reset del entorno

```bash
python -m src.cli reset
# o
./scripts/reset.sh
```

`reset` limpia **solo el entorno de desarrollo configurado**:

- elimina las colecciones (e índices) de la base `MONGO_DB` en MongoDB;
- elimina todos los nodos y relaciones de Neo4j, conservando las restricciones de unicidad;
- no toca otras bases ni volúmenes.

Si se necesita un entorno totalmente desde cero, se pueden borrar también los volúmenes:

```bash
docker compose down -v
docker compose up -d --wait
python -m src.cli seed
```

---

## Estructura del proyecto

```text
.
├── .devcontainer/          # Codespaces con Docker-in-Docker
├── data/                   # 9 CSV de entrada
├── docker/mongo-init/      # inicialización idempotente del replica set
├── docker-compose.yml      # MongoDB, mongo-init y Neo4j
├── docs/
│   ├── distribucion_datos.md
│   └── resolucion_queries.md
├── scripts/
│   ├── seed.sh
│   └── reset.sh
├── src/
│   ├── cli.py              # comandos del cliente
│   ├── config.py
│   ├── db/                 # conexión y espera de servicios
│   └── loaders/            # CSV, MongoDB, proyección Neo4j
├── tests/
├── .env.example
└── pyproject.toml
```
