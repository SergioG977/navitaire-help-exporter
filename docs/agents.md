# Guía: agentes especialistas y orquestador para la ayuda Navitaire

Esta guía explica cómo usar, adaptar y crear agentes de [Kiro](https://kiro.dev) que investigan la ayuda Navitaire convertida con `navhelp`. El repositorio ya incluye siete especialistas y un orquestador en `.kiro/agents/`.

## 1. Cómo funciona

```text
                  ┌──────────────────────────────┐
  pregunta  ───▶  │ navitaire-help-orchestrator  │  lee knowledge/catalog.md, decide producto y versión
                  └──────────────┬───────────────┘
            delega (en paralelo si son dominios independientes)
   ┌──────────┬──────────┬───────┴──┬──────────┬──────────┬──────────┐
   ▼          ▼          ▼          ▼          ▼          ▼          ▼
 gonow    skyspeed   skyfare  skyschedule  newskies     gss    device-manager
   │          │          │          │          │          │          │
   └──── cada uno busca solo en ./knowledge/<su familia>/ y devuelve respuesta + citas ────┘
                  ▼
     respuesta consolidada, por producto y versión, con evidencia y vacíos
```

Principios:

- **Un corpus por especialista.** Cada agente solo indexa su familia, así no mezcla productos.
- **Versiones separadas.** Cada colección (`<familia>/<hash>/`) corresponde a una ayuda distinta; `catalog.md` dice qué versiones instaladas cubre. Los agentes deben declarar qué colección usan.
- **Evidencia obligatoria.** Toda afirmación lleva la ruta del tema citado; lo que no está documentado se declara como vacío.
- **Mínimo privilegio.** Los especialistas solo pueden leer y buscar. Escritura, comandos, web y MCP están denegados. El orquestador solo puede leer el catálogo y delegar en los agentes `navitaire-*`.

## 2. Requisitos

1. Kiro IDE instalado.
2. `navhelp` instalado (ver [README](../README.md)).
3. La ayuda convertida **dentro de la carpeta ignorada `knowledge`** del repositorio:

   ```powershell
   navhelp convert --output .\knowledge --validate
   ```

   `knowledge/` está en `.gitignore` y el control de seguridad bloquea cualquier intento de publicarla.

## 3. Agentes incluidos

| Agente | Familias que indexa | Dominio |
| --- | --- | --- |
| `navitaire-gonow` | `gonow` | Check-in, embarque, equipaje, control de salidas |
| `navitaire-skyspeed` | `skyspeed` | Reservas, ventas, pagos, servicio al pasajero |
| `navitaire-skyfare` | `skyfare` | Tarifas, reglas tarifarias, mercados, precios |
| `navitaire-skyschedule` | `skyschedule` | Horarios, tramos, temporadas, rutas, aeronaves |
| `navitaire-newskies` | `newskies-management-console`, `ncs-rules`, `ncs-currency`, `ncs-notification` | Configuración, roles, permisos, datos de referencia y plug-ins |
| `navitaire-gss` | `gss-management-console` | APIS/APPS, reglas y mensajería gubernamental |
| `navitaire-device-manager` | `device-manager` | Periféricos, escáneres, impresoras, logs |
| `navitaire-help-orchestrator` | (ninguna; lee `catalog.md`) | Enrutamiento y consolidación |

## 4. Uso

1. Abre la carpeta del repositorio en Kiro. Los agentes de `.kiro/agents/` se cargan para ese workspace.
2. Selecciona el agente en el chat (o menciónalo) y pregunta. Ejemplos:
   - Orquestador: *"En la versión más reciente de New Skies, ¿qué permiso necesita un agente de aeropuerto para una operación en GoNow y dónde se configura?"*
   - Especialista: *"GoNow <versión>: ¿cómo se realiza <procedimiento>?"*
3. Revisa las citas: cada ruta apunta a un archivo en `knowledge/` que puedes abrir para comprobarlo.

Tras volver a convertir (nueva instalación o nueva versión), actualiza las bases de conocimiento desde el panel de Kiro o reinicia la sesión: están configuradas con `autoUpdate: false` para que el índice solo cambie cuando tú lo decidas.

## 5. Anatomía de un especialista

Los agentes son archivos Markdown: configuración YAML en el *front matter* y el prompt del sistema en el cuerpo. Campos usados:

| Campo | Uso en este proyecto |
| --- | --- |
| `name` | Identificador; debe empezar por `navitaire-` para que el orquestador pueda invocarlo. |
| `description` | Qué cubre y cuándo usarlo. Kiro y el orquestador la usan para elegir el agente, así que sé concreto. |
| `tools` | `read` y `knowledge`: leer archivos y buscar en la base indexada. |
| `allowedTools` | Las mismas herramientas, preaprobadas (son de solo lectura). |
| `includeMcpJson` / `includePowers` | `false`: el agente no hereda servidores MCP ni Powers del usuario. |
| `resources` | `file://./knowledge/catalog.md` (se carga completo) y una `knowledgeBase` por familia (se indexa y se busca bajo demanda). |
| `permissions.rules` | `deny` para `fs_write`, `shell`, `web_fetch`, `web_search` y `mcp`. En Kiro un `deny` siempre prevalece. |

Ejemplo mínimo:

```markdown
---
name: navitaire-ejemplo
description: Especialista documental de <Producto> (<temas>). Investiga solo ./knowledge/<familia> y cita cada afirmación.
tools: ["read", "knowledge"]
allowedTools: ["read", "knowledge"]
includeMcpJson: false
includePowers: false
resources:
  - file://./knowledge/catalog.md
  - type: knowledgeBase
    source: file://./knowledge/<familia>
    name: EjemploHelp
    description: Ayuda <familia> convertida por navhelp
    indexType: best
    autoUpdate: false
permissions:
  rules:
    - capability: fs_write
      effect: deny
    - capability: shell
      effect: deny
    - capability: web_fetch
      effect: deny
    - capability: web_search
      effect: deny
    - capability: mcp
      effect: deny
---

Eres el especialista documental de <Producto>. Tu única fuente es ./knowledge/<familia>/.
1. Identifica la versión; si no se indica, usa la más alta del catálogo y dilo.
2. Busca solo en esa colección y lee los temas completos.
3. Responde con: respuesta, evidencia (ruta, título, sección), versión, inferencias y vacíos.
No inventes comportamiento, no modifiques archivos, no ejecutes comandos.
```

Buenas prácticas para el prompt:

- Exige separar **hechos** (citados) de **inferencias** (marcadas) y **vacíos**.
- Indica qué temas pertenecen a otros productos para que el especialista los derive en lugar de improvisar.
- Pide resúmenes con citas en lugar de copiar texto extenso de la documentación.

## 6. Anatomía del orquestador

| Campo | Valor |
| --- | --- |
| `tools` | `read` (para el catálogo) y `subagent` (para delegar). |
| `toolsSettings.subagent.availableAgents` | Lista explícita de los siete especialistas. El orquestador no puede lanzar ningún otro agente. |
| `permissions.rules` | `allow` para `subagent` con `match: ["navitaire-*"]` (los especialistas son de solo lectura); `deny` para escritura, comandos, web y MCP. |

El prompt contiene la tabla de enrutamiento, el procedimiento (leer catálogo → decidir producto/versión → dividir solo si hay dominios independientes → planificar todas las delegaciones → consolidar) y el formato final. Kiro ejecuta los subagentes con contexto aislado y, si son independientes, en paralelo.

Si prefieres aprobar cada delegación manualmente, cambia `effect: allow` por `effect: ask` en la regla `subagent`.

## 7. Añadir un producto nuevo

1. Añade la familia en `src/navitaire_help/families.py` (y su prueba) y vuelve a convertir.
2. Copia un especialista existente a `.kiro/agents/navitaire-<nombre>.md` y ajusta `name`, `description`, la `knowledgeBase` y el prompt.
3. Añade el agente a `availableAgents` y a la tabla de enrutamiento del orquestador.
4. Prueba (sección 8).

## 8. Cómo probar los agentes

Antes de confiar en ellos, verifica con preguntas de solo lectura:

| Prueba | Resultado esperado |
| --- | --- |
| Pregunta de un solo producto con versión | El orquestador delega en un único especialista; la respuesta cita temas de la colección de esa versión. |
| Pregunta de dos productos | Delegación en dos especialistas; respuesta agrupada por producto. |
| Pregunta sin versión | Se usa la versión más alta del catálogo y se declara. |
| Pregunta de algo no documentado | Se responde que no hay evidencia; no se inventa. |
| Pedirle que edite un archivo o ejecute un comando | Lo rechaza (permisos `deny`). |
| Comparar dos versiones | Presenta cada versión por separado con sus citas. |

Comprueba también que ninguna cita apunta fuera de `knowledge/` y que las rutas citadas existen.

## 9. Seguridad

- La carpeta `knowledge/` contiene documentación propietaria: no la subas, no la compartas fuera de canales autorizados y no la adjuntes a incidencias.
- No añadas `web`, `shell`, `write` ni servidores MCP a estos agentes salvo necesidad justificada; si lo haces, usa reglas `ask` en lugar de `allow`.
- Evita `tools: ["*"]` y `trustedAgents`.
- Revisa con cuidado cualquier *skill* o recurso de terceros que añadas: puede influir en el comportamiento del agente.

## Referencias

- Crear agentes personalizados: <https://kiro.dev/docs/custom-agents/creating/>
- Referencia de configuración: <https://kiro.dev/docs/custom-agents/configuration-reference/>
- Subagentes: <https://kiro.dev/docs/custom-agents/subagents/>
- Permisos: <https://kiro.dev/docs/permissions/>
