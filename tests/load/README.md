# Testing de carga para Tecman

## Objetivo
Validar si Tecman soporta una apertura gradual hacia las 112 sucursales sin degradarse ni caerse.

## Qué conviene probar

### 1. Smoke test funcional
Antes de medir carga, confirmar manualmente:
- login sucursal
- acceso a panel sucursal
- creación de ticket
- acceso a S&H sucursal
- login Patricia
- panel S&H
- login admin
- admin > S&H

### 2. Load test
Simular tráfico razonable:
- 10 usuarios virtuales
- 25 usuarios virtuales
- 50 usuarios virtuales
- 100 usuarios virtuales
- 112 usuarios virtuales

Medir:
- tiempo medio de respuesta
- p95 / p99
- porcentaje de errores
- endpoints más lentos

### 3. Stress test
Subir por encima de lo esperado:
- 150 usuarios
- 200 usuarios
- 300 usuarios

Objetivo:
- detectar punto de degradación
- ver si Render devuelve 502/504
- entender el cuello de botella

## Endpoints sugeridos para testear primero
- `/`
- `/suc/login`
- `/nuevo-ticket`
- `/syh/login`
- `/admin/login`

## Recomendación importante
Idealmente hacer esto sobre:
- una copia de Render
- o una instancia staging

No conviene hacer stress fuerte sobre producción porque:
- ensucia datos
- genera tickets falsos
- puede frenar usuarios reales

## Corrida inicial sugerida
1. 10 usuarios durante 2 minutos
2. 25 usuarios durante 3 minutos
3. 50 usuarios durante 5 minutos
4. 100 usuarios durante 5 minutos
5. 112 usuarios durante 5 minutos

## Señales de alerta
- p95 > 2 segundos en paneles simples
- errores > 1%
- 502 / 504 de Render
- timeouts al crear ticket
- problemas al subir archivos

## Próximo paso lógico
Además de este script básico:
- testear login real con usuarios de sucursal
- simular creación de tickets
- separar pruebas de lectura vs escritura
