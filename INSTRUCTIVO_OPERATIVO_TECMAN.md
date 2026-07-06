# Instructivo operativo Tecman

## Objetivo

Tecman se usa como tablero unico de mantenimiento. Cada problema de sucursal debe entrar como ticket, quedar asignado a un responsable y cerrarse con evidencia.

## Roles

- Sucursal: carga problemas, fotos y pedidos de materiales.
- Admin mantenimiento: prioriza, reasigna, responde y controla avance.
- Proveedor con abono fijo: ve sus trabajos asignados, informa visitas, avances, bloqueos y cierre.
- Compras: gestiona stock, materiales y envios.
- S&H: controla habilitaciones, matafuegos, permisos y documentacion.
- Equipo Central: ejecuta trabajos internos cuando admin lo define.

## Proceso establecido

1. La sucursal abre un ticket desde el portal de sucursal.
2. El sistema asigna automaticamente segun categoria, zona y proveedor de abono.
3. Admin revisa prioridad y corrige asignacion si corresponde.
4. Si el trabajo corresponde al proveedor de abono fijo, el proveedor entra a `/proveedor/login`.
5. El proveedor marca el ticket como recibido.
6. Si ya sabe fecha de visita, marca planificado e informa fecha.
7. Durante la visita puede cargar fotos antes/despues, notas, informe o presupuesto adicional.
8. Si no puede resolver, marca el bloqueo y explica motivo: materiales, autorizacion, local cerrado u otro.
9. Cuando termina, marca hecho. El ticket queda resuelto con historial.
10. Admin revisa casos resueltos y cierra lo que ya no requiere seguimiento.

## Reglas de uso para proveedores con abono fijo

- Deben entrar todos los dias habiles y revisar pendientes.
- Cada ticket recibido debe tener una accion registrada: recibido, planificado, relevado, bloqueado o hecho.
- No se deben resolver trabajos por WhatsApp sin actualizar Tecman.
- Si pide materiales, debe dejarlo escrito en el ticket.
- Si el trabajo no esta incluido en el abono, debe cargar presupuesto adicional antes de avanzar.
- Todo trabajo terminado debe tener evidencia minima: nota de cierre y, cuando aplique, foto despues.

## Cuenta de proveedor para piloto

- `ceyh`: CEYH.

La clave se configura con `PROVEEDOR_PASSWORD`. Si no esta configurada, en desarrollo usa `prov2026`.

## Sucursales del piloto CEYH

- Sucursal 195.
- Sucursal 213.
- Sucursal 014.
- Sucursal 211.
- Sucursal 036.

El piloto queda limitado a estas sucursales. El objetivo es probar carga de tickets reales, seguimiento admin, respuesta de CEYH, evidencia de cierre y cruces con S&H antes de abrir Tecman a toda la red.

## Lanzamiento recomendado

1. Limpiar tickets de prueba.
2. Cargar usuarios finales y clave real de proveedores.
3. Cargar un ticket real por cada flujo: sucursal, proveedor abono, materiales, S&H y equipo central.
4. Hacer piloto con 5 a 10 sucursales durante una semana.
5. Revisar tickets sin respuesta, tiempos de cierre y problemas de carga.
6. Abrir al resto de sucursales cuando el piloto quede estable.
