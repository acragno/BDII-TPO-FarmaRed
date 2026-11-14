# Resolución de las 15 consultas y servicios — FarmaRed

## Arquitectura utilizada

MongoDB es la fuente de verdad y concentra las escrituras operativas. Neo4j mantiene una proyección de lectura de clientes, sucursales, farmacéuticos, recetas, ventas y productos. Los servicios de escritura consultan MongoDB; las lecturas de Neo4j reflejan los cambios una vez procesada la sincronización.

Las siguientes son estrategias de implementación, no código ejecutable ni resultados de ejecución. Cada consulta debe exponerse en una función o módulo separado (`q01` a `q15`).

## Tabla de resolución

| N.º | Consulta o servicio | Motor | Cómo se resuelve | Resultado esperado |
| --- | --- | --- | --- | --- |
| 1 | Productos activos con todos los datos del proveedor | MongoDB | Filtrar `productos.activo = true`; realizar `$lookup` con `proveedores` usando `id_proveedor`; incorporar el documento completo del proveedor. No agregar un filtro por proveedor activo que el enunciado no pide. | Producto con sus atributos y objeto `proveedor`. |
| 2 | Ventas pendientes con farmacéutico y sucursal | Neo4j | Buscar nodos `Venta` con estado `Pendiente`; recorrer la relación entrante `REGISTRO` desde `Farmaceutico` y `TRABAJA_EN` hacia `Sucursal`. No excluir al farmacéutico por estar inactivo. | ID de venta, total, nombre del profesional, matrícula y sucursal. |
| 3 | Historial completo de un cliente | Neo4j | Recibir `id_cliente`; buscar sus ventas mediante `REALIZO` y sus recetas mediante `TIENE_RECETA`. Construir una lista común de eventos, usando fecha de venta o fecha de emisión de receta, y aplicar `ORDER BY fecha, tipo_evento, id`. Consultar ambas ramas por separado o con una unión para evitar multiplicar ventas por recetas. | Lista cronológica de ventas y recetas, identificando el tipo de evento; opcionalmente con productos de cada venta. |
| 4 | Clientes con más de una receta | Neo4j | Recorrer `Cliente`–`TIENE_RECETA`–`Receta`; agrupar por cliente; contar recetas distintas y conservar cantidades mayores que uno. No filtrar estado de receta ni actividad del cliente. | Cliente y cantidad de recetas registradas. |
| 5 | Farmacéuticos activos y ventas de los últimos 60 días | Neo4j | Partir de todos los `Farmaceutico` activos y usar una búsqueda opcional de sus ventas. Aplicar el rango temporal y `estado <> 'Anulada'` sobre las ventas de la búsqueda opcional. Contar ventas distintas, conservando al profesional aunque no haya coincidencias. | Farmacéutico y cantidad de ventas, incluyendo cero; cuentan pendientes y completadas. |
| 6 | Tratamientos prolongados con próxima dispensa atrasada | Neo4j | Buscar `Receta` con tipo `Tratamiento prolongado`, estado `Vigente`, próxima dispensa no nula y estrictamente anterior a hoy; recorrer `TIENE_RECETA` hacia el cliente y devolver sus datos. | Receta, próxima dispensa y datos del cliente. |
| 7 | Top 5 de productos por unidades vendidas | MongoDB | Filtrar ventas `Completada`; aplicar `$unwind` a `items`; agrupar por producto sumando `cantidad`; ordenar por unidades descendentes y por ID como desempate; limitar a cinco; completar datos con `$lookup` a productos. | Hasta cinco productos con sus unidades vendidas. |
| 8 | Lotes con menos de 50 unidades | MongoDB | Filtrar `stock_lotes.unidades < 50`; realizar `$lookup` con productos y sucursales, y desde producto obtener el proveedor. No excluir vencidos ni productos inactivos, porque el enunciado no lo pide. | Lote, unidades, vencimiento, producto, sucursal y proveedor. |
| 9 | Ventas libres menores a $5.000 | MongoDB | Filtrar `tipo = 'Venta libre'`, `total < 5000` y `estado != 'Anulada'`. | Ventas que cumplen las condiciones, incluidas las pendientes. |
| 10 | Clientes atendidos en una sucursal | Neo4j | Recibir `id_sucursal`; recorrer desde sucursal a farmacéuticos mediante `TRABAJA_EN`, de ellos a ventas mediante `REGISTRO`, y de ventas a clientes mediante `REALIZO`. Usar `DISTINCT` para no repetir clientes. No filtrar actividad del farmacéutico ni agregar exclusiones de estados de venta no pedidas. | Clientes distintos relacionados con ventas de la sucursal indicada. |
| 11 | Ingresos mensuales por farmacéutico | MongoDB | Calcular el inicio del mes actual y del siguiente; filtrar ventas `Completada` en ese intervalo; agrupar por `id_farmaceutico` y sumar `total`; completar los datos del profesional con `$lookup`. No excluir profesionales inactivos. | Farmacéutico e ingresos del mes. La propuesta devuelve quienes tienen ingresos; se puede ampliar con ceros si se documenta. |
| 12 | Clientes sin ventas en el último año | Neo4j | Partir de todos los clientes; seleccionar aquellos para los que no existe una venta relacionada en el intervalo del último año hasta hoy. Incluir clientes que nunca compraron. El enunciado no excluye anuladas: cualquier venta registrada dentro del intervalo impide aparecer. | Clientes sin ventas registradas durante el período. |
| 13 | ABM completo de clientes | MongoDB | Alta: validar datos e insertar, con índice único de DNI. Modificación: actualizar contacto y cobertura por ID. Baja: establecer `activo = false`. Registrar eventos para actualizar la proyección. | Cliente creado o modificado, o rechazo por ID inexistente, DNI duplicado u otra validación. |
| 14 | Registrar una venta completada | MongoDB | Recibir cliente, farmacéutico, ítems, medio de pago y receta opcional; abrir una transacción; validar referencias y reglas; obtener precios del catálogo y calcular total; ejecutar `q15` con la misma sesión; insertar venta; actualizar receta si hay dispensa; guardar eventos y confirmar. | Venta completada y cambios consistentes en receta y lotes, o rechazo sin cambios parciales. |
| 15 | Descontar stock aplicando FEFO | MongoDB | Recibir una venta identificada y su contexto transaccional. Agrupar cantidades por producto; buscar lotes de la sucursal con stock positivo y no vencidos; ordenar por vencimiento e ID; distribuir el consumo entre lotes y descontar con condiciones de disponibilidad. Si cualquier producto no alcanza, abortar toda la transacción compartida con `q14`. | Descuentos por producto y lote, o rechazo sin modificar ningún lote ni dejar venta o receta modificadas. |

## Reglas de implementación relevantes

### Fechas y ordenamiento

- Usar fechas reales en cada motor: BSON Date en MongoDB y tipos temporales en Neo4j. Las fechas de ejemplo de los CSV no deben convertirse en constantes para las consultas temporales.
- Calcular hoy y los límites de los períodos con la fecha del sistema y una zona horaria de negocio consistente.
- Para ventanas que incluyen hoy y datos con hora, utilizar un límite superior exclusivo al inicio de mañana. Para el mes actual, utilizar `[inicio_mes, inicio_mes_siguiente)`.
- Interpretar «último año» como un año calendario hacia atrás y documentar la convención del límite inferior. No confundirlo automáticamente con 365 días.
- Para FEFO, esta propuesta considera vencido un lote si `vencimiento < hoy`; explicitar esta convención. Si se define otra interpretación del día de vencimiento, aplicarla en forma consistente.
- En el historial, ordenar recetas por `fecha_emision` y ventas por `fecha`. No unir cada receta con cada venta del cliente, porque generaría duplicaciones.

### Integración de los servicios 14 y 15

1. `q14` inicia una sesión y una transacción de MongoDB.
2. Valida cliente existente y activo; farmacéutico existente y activo, asociado a una sucursal tipo `Farmacia`; productos existentes y activos; y cantidades válidas. Para productos bajo receta, valida receta del mismo cliente, vigente y con dispensas disponibles.
3. Obtiene los precios actuales, agrupa ítems repetidos cuando corresponda y calcula el total sin confiar en un total enviado por el cliente.
4. Inserta la venta dentro de la transacción, todavía invisible externamente. `q15` la obtiene usando esa misma sesión y aplica FEFO sobre sus ítems. Si se prefiere insertar al final, `q15` puede trabajar con el objeto de venta todavía no persistido; debe documentarse la interfaz elegida.
5. `q15` controla el resultado de cada decremento condicionado a disponibilidad y registra los lotes consumidos. Si falla una validación o falta stock, el error se propaga y se aborta la transacción completa.
6. Se incrementa la receta una vez por dispensa, no por ítem. Si quedan dispensas autorizadas, se fija `proxima_dispensa` a 30 días de la dispensa; si se agotan, pasa a `Completada` y se vacía la próxima fecha. Simples y archivadas se completan con su única dispensa.
7. Se marca el stock de la venta como aplicado y se insertan los eventos de sincronización en `outbox`.
8. Se confirma la transacción. Ante conflictos transitorios se reintenta la operación completa; ante errores de negocio se devuelve el rechazo.

El indicador de stock aplicado y un identificador único de operación evitan descontar dos veces por repetir `q15` o reintentar una petición. No debe implementarse `q15` como un segundo descuento independiente después de que `q14` ya confirmó.

Las transacciones no sustituyen todas las decisiones de concurrencia: para stock y dispensas se necesitan actualizaciones condicionadas y reintentos. Si se permiten bajas o cambios de habilitación simultáneos a una venta y se exige impedir esa carrera, se debe coordinar también la validación de esas entidades mediante escrituras de control o bloqueo lógico en la misma transacción.

### Integridad y sincronización

- Índice único de DNI en MongoDB; controlar el error de duplicado para resolver altas concurrentes correctamente.
- Validar referencias en la aplicación y conservar registros históricos al dar de baja entidades.
- Mantener un único nodo por entidad en Neo4j mediante restricciones de unicidad y actualizaciones idempotentes; conservar los `id_detalle` al proyectar los ítems.
- Sincronizar altas y cambios de todas las entidades que participan en el grafo, incluidos clientes nuevos sin compras y cambios de actividad de profesionales.
- Procesar los eventos pendientes antes de evaluar las lecturas del grafo. El proceso de sincronización no forma parte de la transacción de MongoDB y puede reintentarse.
- La consulta 10 sigue la sucursal del farmacéutico como pide el enunciado. Si se habilitan traslados y se necesita identificar la sucursal histórica de cada venta, debe guardarse esa sucursal al vender y definirse explícitamente esa semántica adicional.

### Evidencia para el informe

Para cada consulta se deben agregar resultados reales obtenidos al ejecutarla. Para `q13`, `q14` y `q15`, mostrar estado antes y después, un caso aceptado y al menos uno rechazado por validación. Incluir un rechazo por stock insuficiente que permita comprobar que no cambió ningún lote ni quedó una venta o receta modificada.
