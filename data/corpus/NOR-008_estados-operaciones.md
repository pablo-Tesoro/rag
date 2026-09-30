---
id: NOR-008
title: Estados de las operaciones en el core bancario
version: "1.2"
date: 2024-11-05
status: vigente
groups: [todos]
---
# Estados de las operaciones en el core bancario

> Documento ficticio de Banco Olvessa (entidad inventada), creado con fines de demostración.

## 1. Objeto

Este documento explica qué significa cada estado que muestra el core bancario para una operación y qué información puede darse al cliente en cada caso.

## 2. Estados de una operación

| Estado | Significado | Qué decir al cliente |
|---|---|---|
| PENDIENTE | La operación está ordenada y pendiente de procesar | Se procesará en el siguiente ciclo, como máximo en 1 día hábil |
| EN_REVISION | La operación está retenida por controles de seguridad o de prevención del blanqueo | Está en revisión; el plazo máximo es de 48 horas hábiles, salvo que una política fije un plazo menor |
| LIQUIDADA | La operación se ha completado | La operación se ha realizado correctamente |
| RECHAZADA | La operación no se ha ejecutado (saldo insuficiente, datos erróneos o controles) | Ofrecer repetirla una vez corregido el motivo |
| DEVUELTA | La operación se ejecutó, pero la entidad del beneficiario o el propio cliente la ha devuelto | El importe se reintegra en la cuenta de origen en un máximo de 2 días hábiles |
| CANCELADA | La operación se anuló antes de ejecutarse | No se ha producido ningún cargo |

## 3. Plazos de liquidación por tipo de operación

- Transferencia SEPA estándar: el siguiente día hábil (D+1).
- Transferencia inmediata: en pocos segundos, salvo retención preventiva (NOR-005, sección 5).
- Transferencia internacional: entre 2 y 4 días hábiles.
- Recibo domiciliado: en la fecha de cargo indicada por el emisor.

## 4. Confidencialidad de las retenciones

Cuando una operación esté EN_REVISION, no reveles al cliente el motivo concreto de la retención ni los controles que se están aplicando. Limítate a informar de que la operación está en revisión y del plazo máximo.

## 5. Consultas sobre operaciones de otras oficinas

Cada empleado solo puede consultar las operaciones de su propia oficina. Si un cliente pregunta por una operación gestionada en otra oficina, indícale que debe dirigirse a su oficina gestora o al servicio de banca telefónica.
