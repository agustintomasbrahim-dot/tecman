# PRD Tecman

## 1. Resumen

Tecman es una aplicacion web interna para centralizar la gestion de mantenimiento de sucursales de Grupo Dabra. Su objetivo es reemplazar el seguimiento disperso por WhatsApp, mails y planillas con un unico flujo trazable: reclamo, asignacion, seguimiento, evidencia, cierre, stock, compras y controles de Seguridad e Higiene.

La app hoy funciona como un monolito Flask con portales separados para sucursales, administracion, proveedores, compras, equipo tecnico y Seguridad e Higiene.

## 2. Objetivos funcionales

- Centralizar todos los reclamos de mantenimiento en tickets.
- Dar visibilidad por sucursal, proveedor, responsable, prioridad y estado.
- Reducir reclamos informales sin historial.
- Ordenar el trabajo de proveedores con abono y equipo interno.
- Registrar evidencia de avance y cierre: notas, fotos, archivos y presupuestos.
- Controlar stock, movimientos, comprobantes y envios de materiales.
- Gestionar documentacion de S&H: habilitaciones, matafuegos, permisos y gestiones.
- Emitir alertas accionables para vencimientos de matafuegos y habilitaciones.
- Exponer APIs internas para resumen operativo, backup y automatizaciones protegidas.

## 3. Usuarios y roles

### Sucursal

- Ingresa al portal de sucursal.
- Carga tickets con categoria, subcategoria, prioridad, descripcion y adjuntos.
- Consulta el estado de sus tickets.
- Responde pedidos de informacion.
- Revisa proveedores asignados.
- Consulta informacion de S&H, matafuegos y permisos propios.

### Administracion de mantenimiento

- Usa el panel admin como tablero principal.
- Revisa, prioriza, reasigna y responde tickets.
- Controla tickets nuevos, abiertos, en progreso, pendientes, resueltos y cerrados.
- Gestiona sucursales, proveedores, busqueda, mapa, reportes y exportaciones.
- Controla pedidos, stock, comprobantes y reportes contables.
- Administra usuarios, accesos y auditoria de login.

### Proveedor

- Ingresa al portal de proveedor.
- Ve trabajos asignados.
- Marca recibido, planificado, relevado, bloqueado o hecho.
- Carga notas, fotos, informes y presupuestos adicionales.
- Informa bloqueos por materiales, aprobacion, local cerrado u otros motivos.

### Compras

- Consulta y actualiza stock.
- Registra entradas, precios y comprobantes.
- Genera envios de materiales a sucursales.
- Consulta historial de envios y comprobantes.

### Equipo tecnico

- Consulta tickets asignados al equipo central.
- Actualiza etapas de trabajo.
- Carga fotos, notas y evidencia.
- Consulta stock y vehiculos.
- Registra informes de vehiculos.

### Seguridad e Higiene

- Consulta panel S&H.
- Gestiona tickets vinculados a S&H.
- Administra matafuegos, habilitaciones, permisos, documentacion y gestiones.
- Genera asistencia desde sucursal.
- Revisa alertas por vencimientos.

## 4. Flujos principales

### 4.1 Alta y seguimiento de ticket

1. La sucursal ingresa al portal.
2. Crea un ticket con categoria, subcategoria, prioridad, descripcion y archivos.
3. El sistema asigna automaticamente segun categoria, subcategoria, zona y proveedor de abono.
4. Administracion revisa el ticket, ajusta prioridad o responsable si corresponde.
5. El responsable actualiza el estado y agrega novedades.
6. La sucursal puede consultar avances.
7. El proveedor o equipo marca el trabajo como resuelto con evidencia.
8. Administracion valida y cierra.

### 4.2 Proveedor con abono

1. El proveedor entra a su portal.
2. Revisa pendientes y nuevos trabajos.
3. Confirma recibido.
4. Informa fecha si el trabajo queda planificado.
5. Carga avances, bloqueos, materiales requeridos o presupuesto adicional.
6. Marca hecho al finalizar.
7. Admin revisa y cierra.

### 4.3 Compras, stock y envios

1. Admin o compras registra stock central.
2. Se cargan precios y movimientos.
3. Se preparan envios a sucursal.
4. Se generan comprobantes y guias.
5. El sistema conserva trazabilidad de movimientos e imputaciones.

### 4.4 Seguridad e Higiene

1. S&H carga o mantiene datos de matafuegos, habilitaciones y permisos.
2. El sistema calcula estados por vencimiento.
3. Se generan alertas internas.
4. Admin puede enviar mails de alertas de matafuegos a sucursales y resumen a responsables.
5. El dispatch evita repetir alertas ya enviadas sin cambios.

## 5. Alcance actual observado

- Portal sucursal: login, selector, panel, alta de tickets, estado, proveedores, S&H, matafuegos y permisos.
- Portal admin: tablero, usuarios, proveedores, sucursales, mapa, busqueda, reportes, exportacion, tickets, pedidos, stock, comprobantes, contable, habilitaciones y S&H.
- Portal proveedor: login, panel y detalle de ticket.
- Portal compras: stock, envios y comprobantes.
- Portal equipo: tickets, stock y vehiculos.
- Portal S&H: panel, matafuegos, tickets, gestiones y edicion por sucursal.
- APIs internas protegidas: resumen, mails, backup y dispatch de alertas.
- Autenticacion: local, Microsoft Entra ID opcional, recupero/cambio de clave, auditoria y bloqueo por intentos.
- Persistencia: JSON local o PostgreSQL mediante `DATABASE_URL`.
- Deploy: Render con Gunicorn y Python 3.11.

## 6. Estado de datos local al 18/08/2026

- Tickets: 0 en `data/tickets.json`.
- Matafuegos: 1.254 registros en 110 sucursales.
- Alertas S&H: 29 alertas activas, 27 de matafuegos y 2 de habilitaciones.
- Dispatch de matafuegos: 27 alertas marcadas como ya enviadas.
- Habilitaciones: 5 registros.
- Usuarios locales: 5 activos.
- Stock central: 21 items.
- Stock por sucursal: 3 sucursales con stock.
- Notificaciones admin: 31.
- Comprobantes: 3.

## 7. Requerimientos funcionales

### Tickets

- Crear ticket desde sucursal con datos minimos obligatorios.
- Adjuntar imagenes, videos cortos y PDF.
- Asignar automaticamente responsable.
- Permitir reasignacion manual por admin.
- Mantener historial de comentarios, estados y evidencias.
- Permitir cierre administrativo separado de resolucion operativa.
- Filtrar y buscar tickets por sucursal, estado, prioridad, categoria, responsable y texto.

### Sucursales

- Cada sucursal debe ver solo su informacion.
- Debe poder consultar tickets propios, proveedores, documentacion S&H y matafuegos.
- Debe poder confirmar recepcion o respuesta cuando aplique.

### Proveedores

- Cada proveedor debe ver solo sus trabajos.
- Debe poder actualizar estados operativos.
- Debe poder cargar evidencia y presupuestos adicionales.
- Debe registrar motivos de bloqueo.

### Compras y stock

- Alta y ajuste de stock central.
- Actualizacion de precios.
- Registro de movimientos.
- Generacion de envios a sucursales.
- Registro de comprobantes.
- Reportes de movimientos e imputaciones.

### S&H

- Alta, edicion y eliminacion de matafuegos.
- Calculo de vencidos y proximos a vencer.
- Alta y seguimiento de habilitaciones.
- Gestion de permisos y documentos.
- Alertas por vencimiento.
- Envio manual de alertas de matafuegos por mail.

### Reportes y APIs

- API de resumen operativo protegida por secreto.
- API de backup de datos protegida por secreto.
- API de resumen de mails protegida por secreto.
- Exportacion admin.
- Reportes contables y de comprobantes.

## 8. Requerimientos no funcionales

- Aplicacion usable desde navegador movil y escritorio.
- Persistencia compatible con JSON local y PostgreSQL en produccion.
- Cargas de archivo hasta 60 MB.
- Sesiones con cookies `HttpOnly`, `SameSite=Lax` y `Secure` en cloud.
- Proteccion CSRF para formularios internos.
- Endpoints sensibles protegidos por `BACKUP_SECRET`.
- No disparar mails masivos automaticamente desde vistas comunes.
- Logs y auditoria para autenticacion.
- Backups descargables de datos JSON.

## 9. Arquitectura tecnica

### Stack

- Backend: Python Flask.
- Servidor produccion: Gunicorn.
- Base de datos opcional: PostgreSQL via Flask-SQLAlchemy.
- Persistencia fallback: archivos JSON en `data/`.
- Templates: Jinja2.
- Autenticacion externa: Microsoft Entra ID via MSAL/JWT.
- Integraciones Google: Gmail, Sheets y Calendar via Google APIs.
- Email saliente: SMTP configurable.
- Deploy: Render.

### Estructura relevante

- `app.py`: aplicacion Flask, rutas, reglas de negocio y helpers.
- `models.py`: modelos SQLAlchemy para PostgreSQL.
- `gauth.py`: credenciales Google.
- `categories_data.py`: categorias y subcategorias.
- `sucursales_data.py`: datos de sucursales, mails y proveedores.
- `templates/`: vistas HTML.
- `data/`: persistencia JSON local.
- `scripts/`: scripts auxiliares.
- `tests/load/`: pruebas de carga/smoke con k6.
- `render.yaml`: configuracion de deploy Render.

### Modelo de datos principal

- Tickets.
- Matafuegos.
- Habilitaciones.
- Comprobantes.
- Movimientos de stock.
- Notificaciones admin.
- Alertas S&H.
- Gestiones S&H.
- Vehiculos de equipo.
- Permisos.
- Presupuestos.
- Retiros y jornadas CEYH.
- Lotes FIFO.
- Transfers.
- Configuracion clave-valor.
- Usuarios, identidades, credenciales locales, reset tokens y auditoria.

## 10. Configuracion de entorno

Variables principales:

- `SECRET_KEY`
- `DATABASE_URL`
- `RENDER`
- `SESSION_LIFETIME_MINUTES`
- `BACKUP_SECRET`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `MAIL_FROM`
- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `GOOGLE_TOKEN_JSON`
- `ENTRA_TENANT_ID`
- `ENTRA_CLIENT_ID`
- `ENTRA_CLIENT_SECRET`
- `ENTRA_REDIRECT_URI`

## 11. Alertas de matafuegos

El sistema calcula alertas desde los registros de matafuegos. Cuando una sucursal tiene matafuegos vencidos o proximos a vencer, se genera una alerta con sucursal, estado, proximo vencimiento, tipos y cantidad.

El envio de mails no esta automatico por defecto. Se dispara desde:

- Boton admin: `/admin/syh/enviar-alertas-matafuegos`.
- Endpoint protegido: `/api/dispatch-alertas-matafuegos?token=BACKUP_SECRET`.

El archivo `data/alertas_syh_dispatch.json` registra que alertas ya fueron enviadas. Si el estado, fecha, cantidad o tipos no cambiaron, el sistema no reenvia. Actualmente el dispatch local esta inicializado con las 27 alertas de matafuegos activas como ya enviadas.

## 12. Riesgos y pendientes

- Replicar el dispatch de alertas en produccion si Render usa PostgreSQL.
- Corregir datos de vencimientos detectados como sospechosos antes de activar avisos reales.
- Ordenar cambios locales sin commitear antes de deploy.
- Definir casilla/remitente SMTP final.
- Limpiar datos de prueba antes del piloto.
- Validar flujo completo con 5 a 10 sucursales piloto.
- Agregar pruebas automatizadas funcionales, no solo carga/smoke.
- Separar progresivamente reglas de negocio de `app.py` si el sistema sigue creciendo.

## 13. Criterios de aceptacion para piloto

- Una sucursal puede crear un ticket real con fotos.
- Admin puede verlo, priorizarlo y reasignarlo.
- Proveedor puede tomarlo, actualizar estado y cargar evidencia.
- Equipo interno puede gestionar tickets propios.
- Compras puede registrar un envio asociado a necesidad operativa.
- S&H puede ver alertas y documentos por sucursal.
- Admin puede cerrar el ticket con historial completo.
- Los mails de alerta de matafuegos no se duplican si no hubo cambios.
- El backup de datos puede descargarse correctamente.

## 14. Roadmap recomendado

### Fase 1: Estabilizacion

- Limpiar datos locales y produccion.
- Corregir fechas y registros sospechosos.
- Confirmar SMTP.
- Replicar dispatch en produccion.
- Hacer prueba controlada de login, ticket, proveedor, cierre y backup.

### Fase 2: Piloto

- Activar 5 a 10 sucursales.
- Usar CEYH como proveedor piloto.
- Medir tickets sin respuesta, tiempos de cierre, bloqueos y uso de evidencia.
- Ajustar categorias, asignaciones y textos operativos.

### Fase 3: Escala

- Abrir progresivamente a toda la red.
- Consolidar reportes gerenciales.
- Automatizar recordatorios y alertas.
- Mejorar dashboard ejecutivo.
- Agregar pruebas automatizadas de regresion.

### Fase 4: Robustez tecnica

- Modularizar backend.
- Formalizar migraciones.
- Mejorar permisos por rol.
- Agregar observabilidad de errores.
- Documentar runbook de deploy, backup y recuperacion.
