# Integración de inventarios TECMAN — 2026-09-28

## Base y fuentes verificadas

- Base Git exacta: `origin/main` en `26a14d166746cdb67ab6fb8b618a3b7965f0de65`.
- Copia local de `matafuegos.json`: 1.254 registros, SHA-256 `dca6f2b2ab25ef7e7eb186067d9ef91c1fc0a462a52dfe31babc39b1d213f769`.
- Diprogom XLS: SHA-256 `72c446190dd5c9b7b1451b86e2efabcbf837dc6763391fe5c6dbac82a3000e92`.
- Fuego Cero XLSX: SHA-256 `4acbab7d11d46bace449bac18b9e4b8938595f2513f2a1b8add2149c389ade58`.
- Captura de generadores declarada: SHA-256 `d11c399b7881eb551938523f673dfaf531842e9c1dcbacaa74fca1234d437753`; manifiesto versionado SHA-256 `5800ea2b79f8e6dd0e45f410a0ca175543a74d41e1f8f69dd588f9cc356e0dd6`.
- Todas las ejecuciones usaron archivos locales, sin red y con outputs distintos de sus inputs.

## Integración funcional seleccionada

- Diprogom final `fccc55b2b168a420ef5145c565ccb94415fab5ef`: su parche funcional ya estaba en la base como commit equivalente `0d23d11f76e8adf79949c70d07c9ef97db0f6e47`; no se duplicó.
- Fuego Cero: `ba573ee733bb6931fd0430ba3ee0a9d81a2fd9c8`, `d699cfc3e073f6084a44eaa1c8ff892d2a277cb7`, `ac8b8d27c5f38129bec064da2fdeafdb30fb0028` y final `2c3d72b6e0d77b742ffd68631aad32100e89795f`.
- Generadores: `899ea15116cbf4155dca4603db932c2e0ecedbf2` y corrección autoritativa `aba5951c899eb58eff50aeba943f9735a6a65f16`.
- No se incorporaron ancestros históricos ajenos ni archivos operativos mutados. Se quitó la llamada automática de migración de generadores al arrancar la aplicación; la migración quedó como comando explícito, con plan y rollback.

## Conciliación secuencial real

Orden aplicado sobre una copia: Diprogom y, sobre esa salida, Fuego Cero.

- Diprogom: 271 actualizaciones + 87 altas = 358 operaciones; 0 bajas; 0 conflictos; total intermedio 1.341.
- Fuego Cero recalculado: 348 actualizaciones + 67 altas = 415 operaciones; 0 bajas; 8 conflictos conservadores; total final 1.408.
- Combinado: 773 operaciones, 154 altas, 619 actualizaciones, 0 bajas, 8 conflictos.
- IDs tocados por ambas etapas: ninguno.
- IDs canónicos duplicados: ninguno.
- Identificadores de proveedor duplicados: ninguno.
- Interacción inesperada: ninguna.
- Invariante: Diprogom tiene exactamente 25 `active_branch_numbers`; Fuego Cero tiene exactamente 35 `confirmed_branch_numbers`; intersección vacía. La herramienta falla si cambia cualquiera de estas condiciones.

Conflictos Fuego Cero conservados, sin eliminación: `fce5e2a3514c` (102), `d2f2d5c73d0a` (125), `d3f9aae75812` y `d4f10fb1f68d` (141), `f264e26de722` y `fc3d41a4d3d2` (147), `c84b059e6d80` y `e18611dd3e11` (165).

## Evidencia reproducible y reversible

- Plan unificado: SHA-256 `2842f768d722c27fe7f54eb5501273824be05f93cf2c2d2f1f672a9ac7f1e9da`; dos dry-runs iniciales fueron byte a byte iguales.
- Salida aplicada: SHA-256 `6d188901b826184f6b3640073d59341448e053bde1a49de628c1b0a7daf6b06e`; hash canónico `ee356d5f3e68166ca7a53dc6d2bdf0f1fd7c1cdde8b58a5131bd744ec0907c72`.
- Segunda ejecución sobre los 1.408 registros: 0 altas, 0 actualizaciones, 0 bajas y 0 operaciones; conserva los mismos 8 conflictos informativos.
- Journal unificado: SHA-256 `7405cc4cc87e347a1c2420b474d3f8eefd32da04600a20ef5fec6b57ebc2b015`.
- Rollback unificado: byte-exacto al input, SHA-256 restaurado `dca6f2b2ab25ef7e7eb186067d9ef91c1fc0a462a52dfe31babc39b1d213f769`.

Generadores se validó por separado sobre el inventario local previo de 21 registros (`05c4c92e51eb944605d9d3f4b1b8bf0452bb77ef051a79f04ad8e972da0b795b`): 21 actualizaciones, 0 altas, 0 bajas, 0 conflictos, total 21; segunda ejecución 0 operaciones; rollback byte-exacto. Plan SHA-256 `863d007fba64e1f0586e3144d39d3adbe7020640804f7234a580e1ae9e4e1ff7`.

Los planes y journals completos se generan fuera del repositorio porque contienen snapshots operativos. El repositorio conserva las herramientas, el manifiesto sanitizado de la captura y este reporte.

## Verificación de código

- Focales Diprogom + Fuego Cero + generadores + integración: 35/35 `OK`.
- Suite completa razonable: 206/206 `OK`.
- `compileall`: `OK`.
- Parseo Jinja: 88/88 plantillas `OK`.
- `git diff --check`: `OK`.
- Hashes de `data/matafuegos.json` y `data/matafuegos_import_state.json` permanecieron iguales; ningún archivo de `data/` ni `static/uploads/` entró al commit.

## Procedimiento pendiente para PostgreSQL en Render

Un deploy de código **no migra PostgreSQL** y no debe presentarse como si lo hiciera. La ejecución real requiere acceso seguro y autorizado a Render, todavía no disponible en esta integración.

1. Detener escrituras operativas o acordar una ventana controlada.
2. Crear y verificar un backup recuperable de PostgreSQL en Render.
3. Exportar el inventario actual a JSON canónico local, sin modificar la base, y registrar conteo + SHA-256.
4. Ejecutar dry-run local con ese export y los hashes exactos de ambas fuentes; revisar el manifiesto, los conflictos y el total.
5. Aprobar explícitamente el SHA-256 del plan. Si el export cambió, descartar el plan y recalcular desde un export nuevo.
6. Aplicar el plan aprobado mediante una migración transaccional controlada, no durante el arranque ni como efecto del deploy. Verificar conteos, IDs y hash lógico antes de confirmar la transacción.
7. Ejecutar nuevamente el conciliador contra un export posterior y exigir 0 operaciones.
8. Conservar backup, export, plan, manifest y journal. Ante desvío, ejecutar rollback controlado y verificar el hash lógico restaurado.
9. Ejecutar la migración explícita de generadores como operación separada, con su propio export, plan, journal, prueba de idempotencia y rollback.

Blockers reales para deploy/migración: autorización de acceso seguro a Render, backup PostgreSQL verificado, export actual de producción, ventana de escritura y aprobación humana del hash del plan recalculado. No hubo push, deploy ni conexión a producción durante esta integración.
