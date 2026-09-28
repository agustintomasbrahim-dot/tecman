# Accesos locales de proveedores de matafuegos

## Cuentas previstas

- `diprogom` → **Diprogom**
- `fuego_cero` → **Fuego Cero**

Ambas cuentas son exclusivamente locales, ingresan por `/proveedor/login` y comienzan deshabilitadas, sin contraseña ni secreto predeterminado. No usan Microsoft Entra ni credenciales internas.

## Activación segura desde Administración

1. Ingresar como administrador y abrir **Usuarios → Proveedores externos** (`/admin/usuarios#proveedores`).
2. En la cuenta prevista, elegir **Restablecer temporal**.
3. Copiar la contraseña temporal que Tecman muestra una sola vez y entregarla por un canal privado al proveedor correcto.
4. Elegir **Habilitar**. Tecman no permite habilitar una cuenta prevista mientras no tenga `password_hash`.
5. Verificar el ingreso por `/proveedor/login` y que el panel muestre únicamente la cartera correspondiente.

Restablecer, habilitar y deshabilitar incrementan la versión de sesión cuando corresponde. Un reset o cambio de estado revoca sesiones anteriores. La contraseña en claro no se persiste ni se incluye en auditoría.

## Carteras autoritativas

- Diprogom: `active_branch_numbers` de `reportes/diprogom_import_preview_2026-09-24.json` (25 sucursales).
- Fuego Cero: `confirmed_branch_numbers` de `reportes/fuego_cero_import_preview_2026-09-28.json` (35 sucursales, incluida 147).

El arranque valida hash, campo, orden, cantidad e intersección vacía de ambas fuentes. Si cualquiera cambia, la aplicación falla de forma explícita antes de exponer una cartera distinta.

El portal lista toda la cartera aunque una sucursal todavía no tenga visitas ni inventario. Cuando existe inventario, sólo lee el módulo canónico de matafuegos y lo filtra por sucursal autorizada. Las visitas y documentos se validan nuevamente contra proveedor, sucursal, equipo e identificadores persistidos en cada ruta.
