# Decisiones de diseño

Una entrada por decisión importante: contexto, alternativas, elección y trade-offs. Están
escritas para poder defenderlas en una entrevista. Se añaden entradas al cerrar cada fase.

---

## D-01. Repositorio dedicado con estructura `src/` y uv

- **Contexto.** Es un proyecto de portfolio: quien lo revise debe entenderlo abriendo la raíz.
- **Alternativas.** Reutilizar un repositorio existente con otro código; estructura plana.
- **Elección.** Repositorio propio (`pablo-Tesoro/rag`), paquete en `src/bank_assistant`,
  gestionado con uv (lockfile reproducible), ruff, mypy estricto y pytest.
- **Trade-offs.** La estructura `src/` obliga a instalar el paquete para importarlo (uv lo
  hace solo), pero evita importar por accidente el código sin instalar y hace que los tests
  prueben lo mismo que se despliega.

## D-02. LLM gratuito: Gemini API en su tier gratuito, detrás de `init_chat_model`

- **Contexto.** Requisito: coste cero. El proveedor debe poder cambiarse por variable de
  entorno sin tocar código.
- **Alternativas.**
  - Modelo barato de pago (p. ej. Claude Haiku 4.5): mejor control de datos, pero cuesta dinero.
  - Ollama con un modelo local pequeño: gratis y sin clave, pero lento en CPU y con tool
    calling poco fiable en modelos de 3–8B; además, su registro está bloqueado en el entorno
    de desarrollo en la nube.
  - Tiers gratuitos de Groq u OpenRouter: bloqueados en ese entorno y con límites cambiantes.
- **Elección.** Gemini API con una clave gratuita de Google AI Studio (sin tarjeta), vía
  `init_chat_model("google_genai:<modelo>")`. El juez de las evals también será configurable.
- **Trade-offs.**
  - El tier gratuito tiene límites de peticiones por minuto y por día: el harness limitará la
    concurrencia y reintentará con backoff, y las ejecuciones completas se harán con cuidado.
  - Google puede usar los datos del tier gratuito para mejorar sus productos. Es aceptable
    porque todo es ficticio; en producción se usaría un tier de pago o un proveedor con
    acuerdo de tratamiento de datos.
  - El "coste estimado" de las evals será 0 real; se podrá calcular el coste equivalente de
    pago con una tabla de precios configurable.

## D-03. Corpus sintético diseñado a partir de las categorías de evaluación

- **Contexto.** Un corpus "bonito" no demuestra nada si no contiene los casos que rompen un
  RAG ingenuo.
- **Alternativas.** Usar documentos reales públicos; generar el corpus con un LLM.
- **Elección.** 13 documentos escritos a mano, cada caso difícil ligado a una categoría del
  dataset (tabla en `data/README.md`): códigos casi idénticos, versión obsoleta y vigente,
  documentos restringidos, inyección indirecta, referencias cruzadas, tabla partida entre
  páginas y una sección más larga que el límite de tokens.
- **Trade-offs.** Es pequeño y no mide escala; a cambio, cada fallo de las evals se puede
  explicar mirando un documento concreto.

## D-04. Etiquetas por documento y sección, no por chunk

- **Contexto.** Las métricas de recuperación necesitan saber qué evidencia es relevante.
- **Alternativas.** Etiquetar ids de chunk, lo más habitual y lo más frágil.
- **Elección.** `(doc_id, sección)`. Un chunk cuenta como relevante si pertenece a ese
  documento y a esa sección o a una subsección.
- **Trade-offs.** Una sección larga dividida en varios chunks cuenta como un único acierto:
  se pierde algo de precisión, pero cambiar el chunking no invalida el dataset.

## D-05. PDFs generados por código y leídos con pdfplumber

- **Contexto.** Hacen falta PDFs con tablas; el corpus debe ser reproducible.
- **Alternativas para generarlos.** Exportar a mano desde un procesador de textos, que no
  es reproducible.
- **Alternativas para leerlos.** PyMuPDF (rápido, licencia AGPL), docling (muy bueno con
  tablas, pero descarga modelos y es pesado), unstructured (pesado).
- **Elección.** `scripts/build_pdfs.py` con reportlab en modo determinista (mismos bytes en
  cada ejecución, así no se dispara una reingesta) y pdfplumber (licencia MIT) para extraer
  texto y tablas.
- **Trade-offs.** Los PDFs "nacidos digitales" son más fáciles que los escaneados: no hay
  OCR. Se deja como limitación.

## D-06. Modelo de permisos: identidad delegada, nunca elegida por el LLM

- **Contexto.** Cada empleado solo puede ver las operaciones de su oficina y los documentos
  de sus grupos, como si cada consulta se hiciera con un token emitido en su nombre (OBO).
- **Alternativas.** Pasar la oficina o los grupos como argumentos de las herramientas;
  filtrar en el prompt ("no le enseñes esto").
- **Elección.**
  - La identidad llega en una cabecera y viaja en el contexto de ejecución.
  - Las herramientas la leen de ahí: el modelo no puede cambiarla.
  - Los filtros van en la consulta a la base de datos.
  - "No existe" y "no tienes permiso" devuelven la misma respuesta, para no revelar que la
    operación existe.
- **Trade-offs.** No hay autenticación real: la cabecera es de confianza. En producción la
  sustituiría un token verificado; el resto del diseño no cambia.

## D-07. Superficie del LLM en español y código en inglés

- **Contexto.** Los usuarios y el corpus están en español; el código debe ser legible para
  cualquier revisor.
- **Elección.** Herramientas, argumentos (`consulta`, `id_operacion`, `categoria`...) y
  prompts en español; identificadores internos en inglés. Los enums traducen: el nombre es
  inglés y el valor es el que devuelve el core (`UNDER_REVIEW = "EN_REVISION"`).
- **Trade-offs.** Hay dos idiomas en el código, pero cada uno con una frontera clara: lo que
  lee el modelo frente a lo que leen los programadores.

## D-08. Cadenas únicas para detectar fugas por código

- **Contexto.** Comprobar con un juez LLM si hubo una fuga es caro e inestable.
- **Elección.** Los documentos restringidos contienen valores únicos y realistas
  (`OLV-SCORE-3`, `COS-7`, `ALERTA-OLV-77`), y el documento con la inyección un canario
  (`OLV-7Q-ALFA`). Si aparecen en la respuesta de quien no debe verlos, el caso falla, sin
  LLM de por medio. Un test comprueba que cada cadena prohibida existe en los datos, para
  que el control no pase siempre sin comprobar nada.
- **Trade-offs.** Solo detecta fugas literales; una paráfrasis del contenido restringido
  escaparía. Por eso también se comprueba que el documento no aparezca entre lo recuperado.

## D-09. Dataset antes que recuperación

- **Contexto.** Sin evaluación, cada cambio en el chunking o en la búsqueda es una opinión.
- **Alternativas.** Escribir el dataset al final, cuando el sistema ya "funciona".
- **Elección.** Redactar el dataset en la fase 1, junto al corpus, y validarlo con tests.
  Así la fase 2 puede medir recall@5 y MRR por modo de búsqueda sin gastar llamadas al LLM.
- **Trade-offs.** Hay riesgo de sobreajustar el sistema a esos 30 casos: por eso 10 se
  reservan como test y no se miran para ajustar nada.

## D-10. Logs JSON sin datos personales

- **Contexto.** Los logs se copian, se indexan y se retienen: son un sitio habitual de fugas.
- **Elección.** Una línea JSON por evento, solo con ids y medidas. Ni preguntas ni
  respuestas ni contenido de documentos: eso va a las trazas, que tienen su propio control
  de acceso. Los ids de empleado se seudonimizan con HMAC y una clave secreta.
- **Trade-offs.** Un hash sin clave no bastaría: los ids vienen de un espacio pequeño y se
  podrían revertir por fuerza bruta. Con HMAC, depurar un caso concreto obliga a pasar por
  las trazas, que es lo deseable.

## D-11. Chunking por estructura, medido en tokens del modelo de embeddings

- **Contexto.** Un chunking de tamaño fijo parte tablas por la mitad, mezcla secciones y
  genera citas imprecisas.
- **Alternativas.** Tamaño fijo con solapamiento; chunking semántico por similitud entre
  frases; un chunk por documento.
- **Elección.**
  - Un chunk nunca cruza una sección: cada chunk tiene una única etiqueta
    `(documento, sección)`.
  - Los bloques (párrafos y tablas) se empaquetan hasta 380 tokens contados con el tokenizador
    del propio modelo (e5-small admite 512).
  - Las tablas van enteras; solo una tabla que no cabe se parte por filas, repitiendo la
    cabecera.
  - Si la prosa sigue en otro chunk de la misma sección, este empieza con las últimas frases
    del anterior (unos 60 tokens de solapamiento).
  - Cada chunk lleva una cabecera con título, id, versión, estado y ruta de secciones, que
    se indexa pero no se cita.
- **Trade-offs.** Hay chunks muy cortos (secciones de dos frases), con menos contexto para el
  embedding; la cabecera lo compensa. Medir con el tokenizador del modelo evita que el
  embedding trunque texto sin avisar.

## D-12. BM25 implementado en SQL sobre un índice invertido

- **Contexto.** La búsqueda léxica es imprescindible para los códigos exactos, y los filtros
  de permisos y de vigencia deben aplicarse en la consulta a la base de datos.
- **Alternativas.**
  - `rank_bm25` en memoria: filtraría en Python, el índice podría quedar desincronizado con
    la base de datos y las estadísticas IDF incluirían documentos restringidos.
  - Búsqueda de texto completo de Postgres (`ts_rank`): no es BM25 (no satura la frecuencia
    ni normaliza por longitud igual) y su analizador parte los códigos por los guiones.
  - ParadeDB `pg_search`: BM25 real en Postgres, pero exige otra imagen y tiene licencia AGPL.
- **Elección.**
  - Una tabla `chunk_terms(term, chunk_id, tf)` y una consulta SQL con la fórmula de Okapi
    BM25 (k1 = 1,2, b = 0,75).
  - Las estadísticas (N, longitud media, df) se calculan solo sobre los chunks visibles para
    el empleado.
  - El analizador léxico es propio: mantiene enteros códigos y números, aplica el stemmer
    Snowball de español, quita tildes y elimina palabras vacías.
  - Un test compara la puntuación de la consulta SQL con una implementación de referencia en
    Python.
- **Trade-offs.** Calcular las estadísticas en cada consulta no escala a millones de
  documentos; ahí se usaría ParadeDB, OpenSearch o Elasticsearch. A cambio, hay una sola
  fuente de verdad, transaccional con la ingesta, y los filtros van en el mismo `WHERE` que la
  búsqueda densa.

## D-13. Fusión con Reciprocal Rank Fusion

- **Contexto.** El modo híbrido combina dos listas cuyas puntuaciones no son comparables:
  BM25 no tiene cota y el coseno está en [-1, 1].
- **Alternativas.** Normalizar las puntuaciones (min-max) y sumarlas con pesos: depende de la
  distribución de cada consulta y obliga a ajustar los pesos.
- **Elección.** RRF con k = 60 (el valor del artículo original), sobre los 20 primeros de cada
  lista. Los empates se resuelven de forma determinista.
- **Trade-offs.** Ignora cuánto mejor es el primero que el segundo; solo cuenta posiciones.
  Es robusto y no tiene nada que ajustar, que con 30 casos de evaluación es una virtud.

## D-14. Embeddings locales con multilingual-e5-small y búsqueda exacta

- **Contexto.** Hace falta un modelo multilingüe pequeño, gratuito y que funcione en CPU.
- **Alternativas.**
  - `paraphrase-multilingual-MiniLM-L12-v2`: más antiguo y con una ventana de solo 128 tokens.
  - `bge-m3`: mejor calidad, pero 568M parámetros, demasiado para CPU.
  - Embeddings por API: coste y dependencia de red.
- **Elección.**
  - `intfloat/multilingual-e5-small` (384 dimensiones, 512 tokens, licencia MIT), con los
    prefijos `query:` y `passage:` con los que se entrenó.
  - Vectores normalizados.
  - En Postgres, una columna `vector` sin dimensión fija (el modelo es configurable) y
    búsqueda exacta sin índice ANN.
- **Trade-offs.** Con unos 70 chunks, la búsqueda exacta es más rápida y precisa que un
  índice aproximado. Con miles de chunks habría que crear un índice HNSW con la dimensión
  fija y tener cuidado con los filtros: la búsqueda iterativa de pgvector 0.8 evita que el
  filtro deje menos de k resultados.

## D-15. Ingesta incremental con huella del índice

- **Contexto.** Reprocesar todo en cada ingesta es lento, y no reprocesar nada al cambiar el
  chunking deja un índice incoherente.
- **Alternativas.** Reindexar todo siempre; comparar fechas de modificación, que cambian al
  clonar el repositorio.
- **Elección.**
  - `content_hash = sha256(huella del índice + bytes del fichero [+ sidecar del PDF])`.
  - La huella incluye la versión del chunker, sus límites, la versión del analizador léxico
    y el modelo de embeddings: cambiar cualquiera de ellos reprocesa todo sin un comando
    aparte.
  - Cada documento se sustituye en su propia transacción.
  - Los documentos que desaparecen del corpus se borran en cascada.
  - Un advisory lock de Postgres impide dos ingestas simultáneas.
- **Trade-offs.** Un cambio de una letra reprocesa el documento entero, no solo el chunk
  afectado. Con documentos de este tamaño es irrelevante, y evita tener que casar chunks
  antiguos con nuevos.

## D-16. Evaluación de la recuperación separada de la del agente

- **Contexto.** Si el agente responde mal, hay que saber si falló la búsqueda o el modelo.
- **Elección.**
  - `evals/retrieval_eval.py` lanza la pregunta tal cual con los permisos del empleado del
    caso y calcula recall@5 y MRR@10 por modo, sin llamar al LLM: es gratis y determinista.
  - La ablación de modos de recuperación sale de aquí sin gastar cuota del tier gratuito.
  - El harness de la fase 4 medirá además lo que el agente recupera realmente con sus
    propias consultas.
- **Trade-offs.** La pregunta cruda no es la consulta que haría el agente (que puede
  reformularla o descomponerla en varios saltos), así que el recall de esta evaluación es una
  cota prudente, no el comportamiento final.

## D-17. Torch solo CPU desde el índice oficial de PyTorch

- **Contexto.** sentence-transformers depende de torch, y la rueda de PyPI para Linux trae
  varios GB de librerías CUDA que este proyecto nunca usa: imagen Docker enorme e
  instalación lenta en CI.
- **Alternativas.**
  - Aceptar la rueda con CUDA.
  - Instalar torch aparte en el Dockerfile, fuera del lockfile, con el riesgo de que las
    versiones diverjan.
  - Prescindir de torch y usar ONNX Runtime (fastembed), lo que cambiaría la librería
    pedida.
- **Elección.** Un índice explícito `pytorch-cpu` en `pyproject.toml` con
  `marker = "sys_platform == 'linux'"`. torch se declara como dependencia directa, porque
  uv solo aplica `[tool.uv.sources]` a dependencias directas. macOS sigue usando la rueda
  de PyPI.
- **Trade-offs.** Todo queda en el lockfile y es reproducible, pero hay que poder llegar a
  `download.pytorch.org` para resolverlo. Torch CPU ocupa 187 MB. ONNX Runtime queda como
  optimización futura, si el arranque o la imagen pesan demasiado.

## D-18. Grafo explícito de cuatro nodos en lugar de un agente prefabricado

- **Contexto.** Hay que poder explicar cada paso y controlar validación, límites, aprobación
  y formato de la respuesta.
- **Alternativas.** `create_agent` de LangChain o `ToolNode` prebuilt: menos código, pero la
  validación, los timeouts, la detección de bucles y la aprobación quedan dentro de
  abstracciones ajenas.
- **Elección.** Un `StateGraph` con cuatro nodos (`agent`, `tools`, `approval`, `finalize`) y
  aristas condicionales, dibujado en el docstring de `agent/graph.py`. El LLM solo decide;
  la ejecución, los permisos y la validación son código nuestro.
- **Trade-offs.** Más código que mantener, a cambio de que cada garantía tenga un sitio
  concreto y un test.

## D-19. Respuesta final estructurada como herramienta `responder`

- **Contexto.** La respuesta debe llevar texto, citas y un indicador de "sin evidencia".
- **Alternativas.**
  - Una llamada extra con `with_structured_output` al final: suma coste y latencia.
  - Forzar la herramienta con `tool_choice`: algunos modelos actuales rechazan el uso
    forzado de herramientas, lo que ataría el código a un proveedor.
- **Elección.** `responder` es una herramienta más, con esquema Pydantic, y el prompt pide
  terminar siempre con ella. Si el modelo contesta en texto libre, se acepta y se marca con
  `terminacion: "texto_libre"`, para verlo en las evals.
- **Trade-offs.** El modelo puede saltarse la herramienta; en lugar de ocultarlo, se mide.

## D-20. Las citas se validan por código contra lo recuperado

- **Contexto.** Un modelo puede citar un documento que no ha leído.
- **Elección.**
  - El estado guarda los chunks recuperados en el hilo.
  - Una cita es válida si su documento y sección, o una sección padre o hija, están entre
    ellos.
  - Si hay citas inválidas, la respuesta vuelve al modelo una vez; si persisten, se
    descartan y quedan registradas en `citas_descartadas`.
  - Con `sin_evidencia`, las citas se vacían.
- **Trade-offs.** Solo comprueba que la fuente se leyó, no que la afirmación esté en ella.
  Eso lo mide el juez de las evals.

## D-21. Aprobación humana con `interrupt()` y escritura idempotente

- **Contexto.** Abrir una incidencia es una escritura. LangGraph reejecuta desde el principio
  el nodo que se reanuda, y un proceso puede caerse entre escribir en la base de datos y
  guardar el checkpoint.
- **Elección.**
  - En el nodo `approval`, antes del `interrupt()`, solo hay lecturas: validar argumentos,
    comprobar que la operación es de la oficina y no repetir una propuesta ya hecha.
  - La escritura va después del `interrupt()`, con clave
    `sha256(thread_id:tool_call_id)` y `ON CONFLICT DO NOTHING`.
  - Solo se propone una incidencia a la vez.
  - Un test simula una caída justo después de escribir y comprueba que al reanudar se crea
    una única incidencia.
- **Trade-offs.** El `tool_call_id` lo genera la integración del proveedor; es estable
  porque se guarda en el checkpoint.

## D-22. Identidad en el contexto de ejecución y propiedad del hilo

- **Contexto.** El modelo no debe poder elegir en nombre de quién actúa, y un empleado no
  debe poder continuar ni aprobar la conversación de otro.
- **Elección.**
  - La cabecera se convierte en un `Employee` y viaja en el `context_schema` de LangGraph en
    cada invocación; no se persiste ni lo ve el modelo como argumento.
  - Los esquemas de las herramientas prohíben campos extra: un argumento `oficina` es un
    error de validación.
  - El estado guarda el dueño del hilo, y la API responde 404 a cualquier otro empleado,
    igual que si el hilo no existiera.
- **Trade-offs.** Sin autenticación real, la cabecera es de confianza (ver D-06).

## D-23. Límites del bucle derivados del historial

- **Contexto.** Un agente puede entrar en bucle o colgarse esperando a una herramienta.
- **Elección.**
  - `recursion_limit` del grafo.
  - Un presupuesto de llamadas a herramientas por turno.
  - Timeout por herramienta con `asyncio.wait_for`.
  - Timeout y reintentos del cliente del LLM.
  - Timeout global por petición en la API.
  - Detección de llamadas repetidas (misma herramienta y mismos argumentos canónicos).
  - Contadores y detección se calculan a partir de los mensajes del turno actual, así que no
    añaden estado.
  - Cada error vuelve al modelo como mensaje de herramienta con una indicación de qué
    corregir.
- **Trade-offs.** Un turno cortado por el presupuesto termina con una respuesta de "no he
  podido completar la consulta". Es explícito, pero puede frustrar en preguntas legítimas
  largas; el presupuesto es configurable.

## D-24. Checkpointer de LangGraph en el mismo Postgres

- **Contexto.** Las conversaciones y las aprobaciones pendientes deben sobrevivir a un
  reinicio.
- **Alternativas.** Redis o SQLite: otra pieza de infraestructura, o nada de concurrencia.
- **Elección.** `AsyncPostgresSaver` en el mismo Postgres, con un pool propio en modo
  autocommit y sin prepared statements, como pide la librería. Un test de integración pausa
  una aprobación, levanta una instancia nueva de la app y la reanuda.
- **Trade-offs.** Un único Postgres concentra índice, core simulado, incidencias y
  checkpoints: sencillo de operar, pero es un único punto de fallo.

## D-25. Liveness frente a readiness, y arranque sin LLM

- **Contexto.** Sin clave del LLM, el cliente falla al crearse. Si eso tumba la app, el
  contenedor entra en bucle de reinicios y el error queda enterrado.
- **Elección.**
  - La app arranca igualmente: `/healthz` responde (el proceso vive).
  - `/readyz` devuelve 503 con el detalle de cada comprobación: base de datos, índice
    cargado, core cargado y LLM configurado.
  - `/chat` responde 503 con un motivo claro, sin volcar el error interno.
- **Trade-offs.** El orquestador debe usar `/readyz` para enrutar tráfico; el healthcheck de
  Docker usa `/healthz`.

## D-26. Temperatura por defecto del proveedor

- **Contexto.** La costumbre es fijar temperatura 0 para tener reproducibilidad.
- **Elección.** No se fija por defecto (`LLM_TEMPERATURE` es opcional). La integración de
  Gemini documenta, citando las buenas prácticas de Google, que bajar la temperatura en
  Gemini 3 puede provocar bucles y peor razonamiento. En `gemini-3.5-flash-lite` el muestreo
  es además fijo y la temperatura se ignora.
- **Trade-offs.** Las respuestas no son deterministas. Por eso las evals miden la
  consistencia con `--repeat k` (pass^k) en lugar de suponerla.

## D-27. Logs sin access log

- **Contexto.** El access log de uvicorn registra la IP del cliente, un dato personal.
- **Elección.** Se desactiva en código, sea cual sea el flag de arranque. La app registra un
  evento `chat.turn` por petición con el empleado seudonimizado, el estado, la latencia y
  el número de herramientas usadas. Los logs de uvicorn pasan por el mismo formateador JSON.
- **Trade-offs.** No hay registro por petición de `/healthz` ni de `/readyz`; para eso están
  las métricas del orquestador.

## D-28. Los resultados de las herramientas también son prompt

- **Contexto.** En la prueba real con Gemini, tras rechazar una incidencia, el modelo a
  veces respondía como si faltara la confirmación y volvía a pedirla. El mensaje que recibía
  («El empleado ha rechazado la incidencia: no se ha registrado…») era correcto, pero no
  decía qué contestar. Además, el modelo lo mezclaba con NOR-006 §5 («si el empleado no la
  confirma, la incidencia no se registra»).
- **Alternativas.**
  - Añadir una regla al prompt de sistema: exige una versión `v2` y la regla queda lejos del
    momento en que el modelo lee la decisión.
  - Resolver la respuesta por código tras un rechazo, sin volver a llamar al modelo: es
    fiable, pero quita al modelo el cierre de la conversación (por ejemplo, contestar
    también a otra pregunta del mismo turno).
- **Elección.** Corregir el propio mensaje de la herramienta: dice quién ha decidido
  («ha decidido no abrirla»), que no se ha registrado y que se le diga al empleado, de tú y
  sin pedir otra confirmación. El prompt de sistema sigue en `v1`.
- **Trade-offs.** Estos mensajes no llevan versión propia como los prompts. El commit de
  cada evaluación los identifica, y un test unitario comprueba el contenido del rechazo.
  Con 6 intentos posteriores el error no se repite, pero la redacción varía: la tasa real
  se medirá en la fase 4 con repeticiones (pass^k).
