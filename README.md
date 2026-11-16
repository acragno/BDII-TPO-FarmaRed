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
| `DATA_DIR`       | `./data`                                | Directorio de los CSV originales y su subcarpeta `extra/` |

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
| `outbox-worker` | Build local | — | Sincroniza eventos de MongoDB con Neo4j |
| `neo4j-test` | `neo4j:5.26-community` | `7688` | Neo4j desechable para pruebas de consultas (perfil `test`) |

Los datos persisten en los volúmenes `farmared-mongo-data`, `farmared-neo4j-data` y `farmared-neo4j-logs`.

---

## Carga inicial en MongoDB y Neo4j

El flujo completo se ejecuta con un solo comando:

```bash
python -m src.cli seed
# o, usando el script (levanta Docker primero)
./scripts/seed.sh
```

`seed`, `load-mongodb` y `validate-data` leen los nueve CSV originales de `data/`
y los nueve de `data/extra/`, con **10 registros ficticios nuevos por archivo**.
Se validan juntos los tipos, IDs, DNI, matrículas y referencias antes de escribir
en las bases. Si se configura `DATA_DIR`, también debe contener `extra/` con sus
nueve CSV.

La carga reutiliza el mismo cargador de MongoDB con los registros combinados:
los IDs estables permiten repetirla sin duplicar documentos ni ítems. Luego
se reconstruye la proyección de Neo4j desde MongoDB. Los datos representan una
instantánea; repetir el seed repone los valores de los CSV.

Los registros adicionales toman como referencia el **15/11/2026** e incluyen
stock bajo o agotado, lotes vencidos y próximos a vencer, recetas vencidas,
dispensas atrasadas, clientes sin compras y ventas pendientes y anuladas.

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

### Worker de outbox

`docker compose up -d` inicia un único worker después de que MongoDB y
Neo4j estén saludables y `mongo-init` termine correctamente. La inicialización
de colecciones, índices y grafo sigue realizándose con el CLI (`seed`).

El worker solo consulta `outbox`: lee hasta 50 eventos `Pending`, ordenados por
`created_at` e `_id`. Procesa los siguientes lotes inmediatamente y espera un
segundo cuando no hay eventos, incluso si la colección todavía no existe.
Marca cada evento como `Processed` después del commit en Neo4j. Si falla un
intento, conserva el evento pendiente y reintenta con esperas de 2, 4, 8, 16 y
30 segundos, sin adelantar los eventos posteriores, `attempts` cuenta los intentos de procesamiento.

Las escrituras a Neo4j son idempotentes y la baja conserva el nodo y sus relaciones.

Para ver los intentos: `docker compose logs -f outbox-worker`.

---

## Consultas MongoDB

Estas consultas se ejecutan sobre MongoDB y muestran sus resultados en JSON. Antes de ejecutarlas, levantar los servicios y cargar los datos como se indica en el inicio.

| Consulta | Descripción | Ejecución | Prueba individual |
| --- | --- | --- | --- |
| Q01 | Productos activos con los datos completos de su proveedor habitual (o `null` si no posee), ordenados por ID de producto. | `python -m src.queries.q01` | `pytest tests/test_q01.py` |
| Q07 | Top 5 productos más vendidos en unidades considerando solo ventas completadas, ordenados por unidades e ID de producto. | `python -m src.queries.q07` | `pytest tests/test_q07.py` |
| Q08 | Lotes con stock bajo (menos de 50 unidades), detallando producto, sucursal y proveedor, ordenados por unidades e ID de lote. | `python -m src.queries.q08` | `pytest tests/test_q08.py` |
| Q09 | Ventas de tipo «Venta libre» no anuladas con total menor a $5.000, ordenadas cronológicamente por fecha e ID de venta. | `python -m src.queries.q09` | `pytest tests/test_q09.py` |
| Q11 | Ingresos totales acumulados en el mes actual por farmacéutico a partir de ventas completadas, ordenados de forma decreciente. | `python -m src.queries.q11` | `pytest tests/test_q11.py` |

Q11 calcula la ventana del mes actual usando la fecha/hora del servidor de MongoDB (`$$NOW`, en UTC). Permite pasar opcionalmente `--ahora AAAA-MM-DD` para fijar una fecha de referencia alternativa, interpretada en UTC (por ejemplo, `python -m src.queries.q11 --ahora 2026-10-15`). La fecha/hora de referencia utilizada se informa por `stderr`, de modo que `stdout` conserva el JSON válido.

A diferencia de Neo4j, las pruebas de consultas de MongoDB **no requieren un servicio aislado adicional ni perfiles especiales de Docker**. Se ejecutan contra el contenedor estándar `mongo` utilizando una base de datos efímera (`farmared_test`), que el fixture `mongo_test_db` crea y descarta automáticamente antes y después de cada prueba sin alterar la base de datos operativa `farmared`.

---

## Consultas Neo4j

Estas consultas se ejecutan sobre Neo4j y muestran sus resultados en JSON. Antes de ejecutarlas, levantar los servicios y cargar los datos como se indica en el inicio.

| Consulta | Descripción | Ejecución | Prueba individual |
| --- | --- | --- | --- |
| Q02 | Ventas pendientes con ID, total, nombre y matrícula del farmacéutico y datos de la sucursal. | `python -m src.queries.q02` | `pytest tests/test_q02.py` |
| Q03 | Historial de ventas y recetas de un cliente, ordenado cronológicamente, con fecha, tipo de evento, ID y datos sin repetir fecha ni ID. | `python -m src.queries.q03 C001` | `pytest tests/test_q03.py` |
| Q04 | Clientes con más de una receta distinta, indicando sus datos y la cantidad registrada, sin filtrar estados ni actividad. | `python -m src.queries.q04` | `pytest tests/test_q04.py` |
| Q05 | Farmacéuticos activos y cantidad de ventas de los últimos 60 días, excluyendo anuladas e incluyendo profesionales con cero ventas. | `python -m src.queries.q05` | `pytest tests/test_q05.py` |
| Q06 | Recetas vigentes de tratamiento prolongado cuya próxima dispensa es anterior a hoy, con los datos del cliente. | `python -m src.queries.q06` | `pytest tests/test_q06.py` |
| Q10 | Clientes distintos atendidos en una sucursal, a través del farmacéutico que registró la venta, esté activo o no. | `python -m src.queries.q10 S001` | `pytest tests/test_q10.py` |
| Q12 | Clientes sin ventas registradas en el último año calendario, incluidos quienes nunca compraron; cualquier estado de venta cuenta. | `python -m src.queries.q12` | `pytest tests/test_q12.py` |


Reemplazar `C001` por el ID del cliente a consultar y `S001` por el ID de la sucursal a
consultar. Q05 usa hoy y los 59 días anteriores; Q06 excluye las dispensas
previstas para hoy. Q12 incluye desde la misma fecha del año anterior hasta hoy;
para el 29 de febrero toma el 28 de febrero del año anterior. Las tres calculan
la fecha local del sistema mediante `date.today()`, sin convertir la zona horaria.

Las pruebas de la tabla requieren el servicio aislado `neo4j-test`. Prepararlo una vez antes de ejecutar las pruebas individuales:

```bash
docker compose --profile test up -d --wait neo4j-test
export NEO4J_TEST_URI='bolt://localhost:7688'
export NEO4J_TEST_USER='neo4j'
export NEO4J_TEST_PASSWORD='test_password'
```

---

## Servicios

Estos servicios realizan escrituras en MongoDB y muestran sus resultados en JSON.
Antes de ejecutarlos, levantar los servicios y cargar los datos con `python -m src.cli seed`.
Q13 y Q14 guardan cada operación junto con su evento en `outbox`, dentro de la misma
transacción, para que el worker actualice la proyección de Neo4j. Q15 participa en
la transacción de Q14 y no emite eventos propios.

| Servicio | Descripción | Ejecución | Prueba individual |
| --- | --- | --- | --- |
| Q13 — Alta | Crea un cliente validando sus datos, cobertura y DNI único. | `python -m src.queries.q13 alta --archivo cliente.json` | `pytest tests/test_q13.py` |
| Q13 — Modificación | Actualiza los datos de contacto y cobertura de un cliente existente, validando la cobertura resultante. | `python -m src.queries.q13 modificacion C001 --archivo cambios.json` | `pytest tests/test_q13.py` |
| Q13 — Baja lógica | Establece `activo = false` en un cliente existente, conservando sus datos históricos. | `python -m src.queries.q13 baja C001` | `pytest tests/test_q13.py` |
| Q14 — Venta completada | Valida referencias, calcula precios y total, descuenta stock y actualiza la receta de forma atómica. | `python -m src.queries.q14 --archivo venta.json` | `pytest tests/test_q14.py` |
| Q15 — Stock FEFO | Descuenta lotes vigentes y registra los consumos sin repetir el descuento. | Invocada por Q14 con la misma sesión; sin CLI propio. | `pytest tests/test_q15.py` |

`cliente.json` debe contener los datos del cliente a crear. `cambios.json` debe ser
un objeto JSON con uno o más de estos campos: `email`, `telefono`, `obra_social` y
`nro_afiliado`. Reemplazar `C001` por el ID del cliente que se desea modificar o dar de baja.

`venta.json` requiere `id_venta`, `id_cliente`, `id_farmaceutico`, `fecha`
(`AAAA-MM-DD`), `tipo`, `medio_pago` e `items`. Cada ítem contiene `id_detalle`,
`id_producto` y `cantidad`. Las ventas `Con receta` requieren `id_receta`.
El servicio fija el estado `Completada`, toma los precios del catálogo y calcula
el total; esos campos no se aceptan en la entrada. La próxima dispensa se calcula
a 30 días de la fecha de venta si quedan dispensas del tratamiento prolongado.
Si falla el stock, la receta o el outbox, se revierte toda la operación.

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

### Pruebas de consultas MongoDB

Para ejecutar juntas las pruebas de integración de las consultas de MongoDB (Q01, Q07, Q08, Q09 y Q11), con el servicio `mongo` levantado:

```bash
pytest tests/test_q01.py tests/test_q07.py tests/test_q08.py tests/test_q09.py tests/test_q11.py
```

Estas pruebas utilizan la base de datos efímera `farmared_test` dentro del contenedor habitual de MongoDB y se limpian automáticamente en cada ejecución. No requieren levantar `neo4j-test` ni configurar perfiles de Docker adicionales.

### Pruebas de consultas Neo4j aisladas

El servicio `neo4j-test` no se inicia con los servicios habituales.
Para ejecutar juntas las pruebas de Q02, Q03, Q04, Q05, Q06, Q10 y Q12, usar la preparación indicada en «Consultas Neo4j» y luego:

```bash
pytest tests/test_q02.py tests/test_q03.py tests/test_q04.py tests/test_q05.py tests/test_q06.py tests/test_q10.py  tests/test_q12.py
```

El fixture falla con un mensaje accionable si el servicio no está disponible o
si `NEO4J_TEST_URI` coincide con el endpoint configurado para la aplicación.
Las pruebas limpian únicamente el grafo del servicio aislado. Al terminar, se
puede detener ese contenedor con `docker compose --profile test stop neo4j-test`.

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
├── data/                   # 9 CSV originales
│   └── extra/              # 9 CSV con 10 registros nuevos cada uno
├── docker/mongo-init/      # inicialización idempotente del replica set
├── docker-compose.yml      # MongoDB, mongo-init y Neo4j
├── scripts/
│   ├── seed.sh
│   └── reset.sh
├── src/
│   ├── cli.py              # comandos del cliente
│   ├── config.py
│   ├── db/                 # conexión y espera de servicios
│   ├── loaders/            # CSV, MongoDB, proyección Neo4j
│   └── queries/            # consultas y servicios por número (q01 a q15)
├── tests/
├── .env.example
└── pyproject.toml
```
