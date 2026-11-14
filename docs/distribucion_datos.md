# Distribución de datos — FarmaRed

## Motores elegidos

**MongoDB + Neo4j**, correspondientes a los paradigmas de documentos y grafos. La distribución es por responsabilidad: MongoDB mantiene los datos operativos originales; Neo4j conserva una proyección para consultas de relaciones e historiales.

## Tabla de distribución

| Datos | MongoDB: fuente de verdad | Neo4j: proyección de lectura | Justificación |
| --- | --- | --- | --- |
| Clientes | Colección `clientes` con todos los atributos. Altas, modificaciones y bajas lógicas. Índice único sobre `dni`. | Nodos `Cliente` con ID y atributos necesarios para las consultas, incluidos clientes sin ventas. | MongoDB centraliza el ABM y las validaciones al vender. Neo4j permite recorrer compras y recetas, y detectar ausencia de relaciones. |
| Sucursales | Colección `sucursales` completa. | Nodos `Sucursal` con ID, nombre, tipo y demás datos requeridos. | Se valida el tipo de sucursal en MongoDB; en el grafo se relacionan sucursales, farmacéuticos y ventas. |
| Farmacéuticos | Colección `farmaceuticos` completa, con referencia `id_sucursal`. Índice único sobre `matricula`. | Nodos `Farmaceutico` con ID, nombre, apellido, matrícula y activo; relación `TRABAJA_EN` con sucursal. Incluir profesionales sin ventas e inactivos. | MongoDB valida la habilitación para vender; Neo4j resuelve las consultas por profesional y sucursal. Los inactivos siguen vinculados a sus ventas. |
| Proveedores | Colección `proveedores` completa. | No se copian inicialmente. | Las consultas que necesitan proveedor se resuelven en MongoDB con referencias y `$lookup`. La baja frecuencia de cambios no exige otro motor. |
| Productos | Colección `productos` completa; referencia `id_proveedor`. | Nodos `Producto` con ID, nombre y atributos descriptivos necesarios. | El catálogo original permite validar existencia, actividad y precio. El grafo relaciona los productos con las ventas del cliente. |
| Stock por lote | Colección `stock_lotes`: un documento por `id_lote`, con producto, sucursal, número de lote, unidades y vencimiento. | No se copia. | Mantener los lotes junto con ventas y recetas permite aplicar FEFO y confirmar o revertir todos los cambios en una sola transacción. |
| Recetas | Colección `recetas` completa, con referencia al cliente y control de dispensas. | Nodos `Receta` con atributos necesarios; relaciones con cliente y ventas que la utilizan. | MongoDB controla las dispensas dentro de la transacción de venta. Neo4j permite historial, conteos y seguimiento de tratamientos. |
| Ventas | Colección `ventas`: cabecera, referencias, total, estado y array `items`. Puede registrar también qué lotes se consumieron. | Nodos `Venta` con ID, fecha, tipo, medio de pago, total y estado; relaciones con cliente, farmacéutico, receta opcional y productos. | El documento representa la unidad de compra. El grafo permite navegar desde las personas hacia sus operaciones y productos. |
| Detalle de ventas | Embebido en `ventas.items`: `id_detalle`, `id_producto`, `cantidad`, `precio_unit`. No requiere una colección aparte. | Relaciones `INCLUYE` entre venta y producto, con `id_detalle`, cantidad y precio histórico. | La cantidad variable de ítems se adapta al modelo documental. El precio vendido se conserva aunque cambie el catálogo. |
| Eventos de sincronización | Colección técnica `outbox`, escrita en la misma transacción que los cambios operativos. | Los eventos actualizan los nodos y relaciones; no requieren un nodo equivalente. | Permite reintentar la sincronización sin perder cambios confirmados ni depender de una escritura simultánea en dos motores. |

## Relaciones en Neo4j

| Origen | Relación | Destino | Propiedades de la relación |
| --- | --- | --- | --- |
| `Cliente` | `REALIZO` | `Venta` | — |
| `Cliente` | `TIENE_RECETA` | `Receta` | — |
| `Venta` | `UTILIZA` | `Receta` | —; solo si la venta tiene receta |
| `Farmaceutico` | `REGISTRO` | `Venta` | — |
| `Farmaceutico` | `TRABAJA_EN` | `Sucursal` | — |
| `Venta` | `INCLUYE` | `Producto` | `id_detalle`, `cantidad`, `precio_unit` |

## Consistencia e integridad

- Todas las modificaciones de negocio se realizan en MongoDB. Los datos del grafo no se usan para autorizar ventas ni descontar stock.
- Los servicios 14 y 15 comparten una única transacción y sesión de MongoDB. Si falla el stock, se revierten venta, receta, lotes y eventos asociados.
- MongoDB se despliega como replica set para habilitar transacciones entre documentos; una instancia standalone no alcanza.
- Los IDs originales de los CSV se conservan en ambos motores. En MongoDB pueden utilizarse como `_id`; en Neo4j se crean restricciones de unicidad para los identificadores de cada etiqueta.
- MongoDB no resuelve automáticamente las referencias: los servicios validan las entidades relacionadas. El DNI único se garantiza con un índice único, no solamente con una búsqueda previa.
- Un proceso lee `outbox` y actualiza Neo4j de manera idempotente. Se controla el orden o la versión por entidad para no sobrescribir datos nuevos con eventos antiguos.
- Neo4j tiene consistencia eventual respecto de MongoDB. Antes de demostrar las consultas se espera a que la proyección alcance los cambios confirmados. Ante un fallo de sincronización, se reintenta o se reconstruye desde MongoDB.
- Las bajas conservan nodos, documentos y relaciones históricas. Se utiliza `activo = false` donde corresponde; no se borran recetas ni ventas históricas.
- Se crean índices para búsquedas por cliente, farmacéutico, fecha y estado, y un índice de lotes por sucursal, producto y vencimiento.

## Carga inicial

La carga reproducible primero incorpora los CSV y los registros adicionales a MongoDB, agrupa los detalles dentro de cada venta y luego construye la proyección de Neo4j. Se usan los IDs estables para que repetir la carga no duplique registros. Los registros adicionales deben cumplir el mínimo de la consigna y cubrir los casos borde pedidos.

## Alcance de la elección

No se agregan MySQL, Cassandra ni Redis a esta propuesta. MongoDB cubre documentos, agregaciones y transacciones; Neo4j cubre consultas de relaciones. Esta arquitectura repite algunos datos y requiere sincronización, a cambio de mantener toda la escritura crítica en un único motor. Para los datasets pequeños del TP, no se presupone que el grafo será más rápido: la justificación es el modelo de consulta y la separación de responsabilidades.
