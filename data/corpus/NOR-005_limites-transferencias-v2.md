---
id: NOR-005
title: Política de límites operativos de transferencias
version: "2.0"
date: 2025-04-01
status: vigente
groups: [todos]
supersedes: NOR-004
---
# Política de límites operativos de transferencias

> Documento ficticio de Banco Olvessa (entidad inventada), creado con fines de demostración.

## 1. Objeto y ámbito

Esta política fija los límites diarios que se aplican a las transferencias ordenadas por los clientes particulares, tanto en oficina como en banca digital, con el fin de reducir el riesgo de fraude y de errores operativos.

Esta versión 2.0 entra en vigor el 1 de abril de 2025 y sustituye a la versión 1.0 (NOR-004), que queda obsoleta. Los cambios principales son la subida de los límites, la eliminación de la vía telefónica para ampliar límites y la retención preventiva de transferencias inmediatas a beneficiarios nuevos.

## 2. Límites diarios por canal

| Tipo de transferencia | Canal | Límite diario por cliente |
|---|---|---|
| Transferencia inmediata | Oficina | 5.000 € |
| Transferencia inmediata | Banca digital | 2.000 € |
| Transferencia SEPA estándar | Banca digital | 15.000 € |
| Transferencia SEPA estándar | Oficina | Sin límite operativo (sujeta a la sección 3) |
| Transferencia internacional | Oficina | 25.000 € |

Los límites se calculan por cliente y día natural, sumando todas las transferencias del mismo tipo y canal. Las comisiones de cada tipo de transferencia están en las Tarifas de transferencias y cambio de divisa (NOR-003).

## 3. Autorizaciones reforzadas

Las transferencias ordenadas en oficina por un importe superior a 15.000 € requieren la validación del director o directora de la oficina mediante segunda firma en el terminal. Si el importe supera los 60.000 €, se necesita además la autorización del área de Operaciones Centrales, que se solicita desde el propio terminal y se resuelve en un máximo de 2 horas hábiles.

Cuando la operación implique entrega o ingreso de efectivo, se aplican además las medidas de la política de prevención del blanqueo de capitales (NOR-009).

## 4. Ampliación temporal de límites

El cliente puede solicitar una ampliación temporal de sus límites únicamente por estas vías:

- En oficina, mediante solicitud firmada por el titular.
- En banca digital, confirmando la solicitud con doble factor de autenticación.

No se admiten solicitudes por teléfono ni por correo electrónico. La ampliación tiene una vigencia máxima de 5 días naturales y puede llegar como máximo al doble del límite ordinario.

## 5. Retención preventiva de transferencias inmediatas

Las transferencias inmediatas de más de 1.000 € dirigidas a un beneficiario al que el cliente no haya enviado dinero antes pueden quedar retenidas de forma preventiva, en estado EN_REVISION, durante un máximo de 24 horas. Si en ese plazo no se detecta ninguna incidencia, la transferencia se libera automáticamente. El significado de cada estado se describe en el documento de estados de las operaciones (NOR-008).
