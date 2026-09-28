# Auditoría Fuego Cero — 2026-09-28

## Alcance y huellas

- Base auditada: `data/matafuegos.json`, 1.254 registros, SHA-256 `dca6f2b2ab25ef7e7eb186067d9ef91c1fc0a462a52dfe31babc39b1d213f769`.
- XLSX anterior: SHA-256 `d779d4ce56960264063bda20301da0ae1f630cd098dffa1d3407bd538504deb8`.
- XLSX nuevo: SHA-256 `4acbab7d11d46bace449bac18b9e4b8938595f2513f2a1b8add2149c389ade58` (coincide con la precondición recibida).
- El XLSX de entrada y `data/matafuegos.json` se trataron como solo lectura. Dry-run, apply y rollback se ejecutaron sobre copias temporales; no hubo red, deploy ni escritura en producción.

## Comparación del XLSX

- Misma hoja (`Hoja1`), dimensiones (`50 x 18`), encabezados y estructura.
- De las 900 posiciones de celda comparadas por valor y tipo, hay una sola diferencia de contenido: `E22`, sucursal `147` / `DEXTER JUMBO PILAR`, cambia vencimiento de `2025-01-01` a `2027-03-01`.
- La fuente anterior auditada ya contiene la sucursal 147 en la misma fila 22, con el mismo nombre, dirección, localidad, propietario y 6 equipos: 5 `ABC x 5` y 1 `HCFC x 5`.
- Los conjuntos de sucursales normalizadas son idénticos: no hay sucursales agregadas ni removidas entre ambos binarios. La nueva versión corrige únicamente el vencimiento y la presentación visual de la 147.
- No hay diferencias normalizadas adicionales en sucursales, nombres, cantidades, tipos/capacidades ni filas sin LOCAL.
- Diferencias de presentación sin efecto en el importador: el nuevo archivo tiene activo el modo de filtro, oculta las filas 2–21 y 23–39, y `E22` pierde el relleno anterior. El autofiltro conserva `A1:Q39`.

## Confirmación explícita de negocio: sucursal 147

- Agustín confirmó el 2026-09-28 la inclusión de `147 — DEXTER JUMBO PILAR` con el alcance exacto de la fuente: 5 `ABC 5 KG` y 1 `HCFC 5 KG`. La regla queda registrada en `BUSINESS_CONFIRMATIONS`, en el plan y en el reporte sanitizado; la sucursal deja de estar pendiente. El conciliador rechaza la ejecución si el nombre o ese alcance exacto no coinciden con la fuente.
- La base contiene 8 registros de la 147: 7 `ABC 5` y 1 `HCFC-123 5`, todos de `google_sheet_matafuegos`, sin proveedor ni actividad operativa.
- Se admite únicamente para la conciliación de la sucursal 147 la equivalencia `HCFC-123 5 KG` → `HCFC 5 KG`. Es una regla acotada por sucursal, documentada y testeada; no modifica el tipo guardado ni crea un alias global.
- Se concilian 5 ABC y el HCFC-123 existente: 6 actualizaciones, 0 altas y 0 bajas en la 147. Los 2 ABC excedentes permanecen intactos como conflictos: `f264e26de722` y `fc3d41a4d3d2`.

## Totales validados

- Total fuente: **509** equipos.
- 35 sucursales numeradas y confirmadas: **415** equipos.
- Pendientes: **0** sucursales y **0** equipos.
- Sin número: **94** equipos: Don Torcuato 1, Garín 93; además permanece la fila cabecera Don Torcuato con 0.

## Dry-run sobre la copia de 1.254 registros

El reporte sanitizado generado quedó en `reportes/fuego_cero_import_preview_2026-09-28.json`.

- 67 altas.
- 348 actualizaciones (342 previas + 6 de la sucursal 147).
- 0 eliminaciones seguras.
- 8 conflictos: los 6 conservadores previos, sin cambios, más los 2 ABC excedentes de la 147.
- 415 operaciones; total proyectado 1.321.
- Conflictos, en orden determinista: `fce5e2a3514c`, `d2f2d5c73d0a`, `d3f9aae75812`, `d4f10fb1f68d`, `f264e26de722`, `fc3d41a4d3d2`, `c84b059e6d80`, `e18611dd3e11`.

## Verificaciones de seguridad y reversibilidad

- Dos dry-runs fueron idénticos byte a byte; SHA-256 del plan: `a2f6f07a397a200f0138888837843853843d992ceaed913ee1cc1090671154cd`.
- SHA-256 del reporte sanitizado: `4daf596186b7e622aca6a86d6996a16ecaed027099d1b6a37707ed92ff47119a`.
- Apply sobre copia: 415 operaciones; salida SHA-256 `c2c41979a69ed69f00bec8cf4ecf96823a3c6255477d31750b13b375faf4596e`.
- Segunda ejecución sobre la salida aplicada: 0 altas, 0 actualizaciones, 0 eliminaciones y 0 operaciones; conserva los mismos 8 conflictos.
- Rollback: 415 operaciones revertidas; contenido JSON exactamente igual al original y hash canónico idéntico `c8f8f8dd64d40016f1198fcc36d9a9046530ae46034ce9b23fc3bf2bf6ac9957`. La serialización agrega únicamente el salto de línea final, por lo que su SHA-256 binario es `ec4204a713ee7eb4bacc53cb91dafad0c8bd0bf177bda372b6138f44a11e208f`.
- Después de todas las verificaciones, las huellas del input y del XLSX permanecieron intactas.

## Pruebas

- Focales: `python3 -m unittest -v tests.test_fuego_cero_import` — 7/7 OK.
- Suite completa: `python3 -m unittest discover -s tests -v` — 169/169 OK.
