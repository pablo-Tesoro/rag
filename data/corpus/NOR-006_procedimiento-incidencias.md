---
id: NOR-006
title: Procedimiento de gestión de incidencias operativas
version: "3.1"
date: 2025-02-20
status: vigente
groups: [todos]
---
# Procedimiento de gestión de incidencias operativas

> Documento ficticio de Banco Olvessa (entidad inventada), creado con fines de demostración.

## 1. Objeto y ámbito

Este procedimiento describe cómo registrar y tramitar las incidencias operativas, es decir, las anomalías en operaciones de clientes que no pueden resolverse en la propia oficina y que requieren la intervención de los servicios centrales.

## 2. Cuándo abrir una incidencia

Abre una incidencia cuando una operación de un cliente de tu oficina presente una anomalía que no puedas corregir tú mismo: un cargo aplicado dos veces, un importe distinto del ordenado, un abono que no llega o una operación que el cliente no reconoce.

Una incidencia no es una reclamación. Si el cliente quiere presentar una queja o una reclamación formal, debe hacerlo a través del Servicio de Atención al Cliente, tal como se explica en la Guía de atención al cliente en oficina (NOR-010, sección 5). Tampoco se abren incidencias para consultas sobre el estado de una operación: para eso basta con consultar el core bancario.

## 3. Categorías y prioridad

Cada incidencia se clasifica en una única categoría, que determina su prioridad:

| Categoría | Descripción | Prioridad |
|---|---|---|
| cargo_duplicado | El mismo cargo se ha aplicado dos o más veces | P2 |
| importe_incorrecto | El importe cargado o abonado no coincide con el ordenado | P2 |
| abono_no_recibido | El abono no ha llegado una vez superado el plazo de liquidación | P3 |
| operacion_no_reconocida | El cliente no reconoce la operación (posible fraude) | P1 |
| otro | Cualquier otra anomalía operativa | P3 |

Si dudas entre dos categorías, elige la de mayor prioridad.

## 4. Datos obligatorios

Toda incidencia debe incluir:

1. El identificador de la operación afectada, con el formato OP- seguido de seis dígitos (por ejemplo, OP-123456).
2. La categoría, según la tabla de la sección 3.
3. Una descripción breve de la anomalía, de un máximo de 500 caracteres.

La descripción no debe contener datos personales del cliente: no incluyas su nombre, su DNI ni el número de cuenta completo. El identificador de la operación es suficiente para que los servicios centrales localicen al cliente.

## 5. Confirmación y registro

Solo pueden abrirse incidencias sobre operaciones de la propia oficina. Toda incidencia propuesta por el asistente virtual requiere la confirmación explícita del empleado antes de registrarse; si el empleado no la confirma, la incidencia no se registra. Una vez registrada, el sistema devuelve un número de incidencia que debe comunicarse al cliente.

## 6. Plazos de resolución

Los plazos máximos de primera respuesta y de resolución dependen de la prioridad de la incidencia y se establecen en el Anexo de niveles de servicio de incidencias y reclamaciones (NOR-007, sección 2).

## 7. Operaciones no reconocidas

Cuando la categoría sea operacion_no_reconocida, además de registrar la incidencia debes ofrecer al cliente el bloqueo inmediato de la tarjeta o del acceso a banca digital implicados. El área de Cumplimiento recibe automáticamente una copia de estas incidencias y actúa según su protocolo interno.
