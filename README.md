# navitaire-help-exporter

Herramienta de línea de comandos (`navhelp`) que **encuentra la ayuda CHM instalada con las aplicaciones Navitaire** (New Skies, GoNow, Government Security y Device Manager), **identifica a qué producto y versión pertenece cada archivo** y la **convierte a Markdown estructurado**, lista para leerla en cualquier editor o para usarla como base de conocimiento de agentes de IA.

Todo el procesamiento es local. La herramienta no envía nada a Internet y este repositorio no contiene, ni debe contener nunca, documentación de Navitaire.

---

## Índice

1. [Qué problema resuelve](#qué-problema-resuelve)
2. [Conceptos básicos](#conceptos-básicos)
3. [Seguridad y confidencialidad](#seguridad-y-confidencialidad)
4. [Requisitos](#requisitos)
5. [Instalación paso a paso](#instalación-paso-a-paso)
6. [Uso rápido](#uso-rápido)
7. [Comandos en detalle](#comandos-en-detalle)
8. [Configuración](#configuración)
9. [Dónde busca y qué excluye](#dónde-busca-y-qué-excluye)
10. [Productos reconocidos](#productos-reconocidos)
11. [Cómo se identifica el producto](#cómo-se-identifica-el-producto)
12. [Cómo se determina la versión](#cómo-se-determina-la-versión)
13. [Estructura de la salida](#estructura-de-la-salida)
14. [Uso con agentes de IA](#uso-con-agentes-de-ia)
15. [Solución de problemas](#solución-de-problemas)
16. [Desarrollo](#desarrollo)
17. [Licencia y atribución](#licencia-y-atribución)

---

## Qué problema resuelve

Las aplicaciones de escritorio de Navitaire incluyen su manual en archivos **CHM** (*Compiled HTML Help*, el formato de ayuda clásico de Windows que se abre con F1). Esos archivos:

- están repartidos en decenas de carpetas de instalación, a menudo **duplicados** (la misma ayuda copiada en cada plug-in);
- conviven en **varias versiones** del mismo producto (por ejemplo varias versiones de New Skies instaladas en paralelo);
- tienen nombres que no siempre dicen de qué producto son ni qué versión documentan;
- no se pueden buscar fácilmente, ni leer desde herramientas modernas o agentes de IA.

`navhelp` resuelve esto en cuatro pasos:

1. **Descubre** todos los `.chm` bajo `C:\Program Files (x86)\Navitaire` (excepto las carpetas excluidas).
2. **Agrupa** los duplicados por contenido (hash SHA-256): cada ayuda distinta se procesa una sola vez.
3. **Clasifica** cada ayuda (qué producto es) y **resuelve la versión instalada** a partir del registro de Windows y de los ejecutables, guardando siempre la evidencia usada.
4. **Convierte** cada ayuda a una carpeta de Markdown con tabla de contenido, índice de palabras clave, imágenes, metadatos y diagnósticos, más un **catálogo** general.

## Conceptos básicos

| Término | Significado |
| --- | --- |
| **Familia** (`family_id`) | Identificador estable del tipo de ayuda: `gonow`, `skyspeed`, `skyfare`… |
| **Producto** | Nombre visible del producto: *GoNow*, *SkySpeed Reservation Manager*, *Fare Manager*… |
| **Colección** | Una ayuda concreta, identificada por el hash de su contenido. Si dos versiones instaladas traen exactamente el mismo CHM, comparten colección. |
| **Versión instalada** | Versión de la aplicación con la que está instalado el CHM (p. ej. `9.1.0.200`). Proviene del registro o del ejecutable. |
| **Versión que indica la ayuda** | Versión mencionada dentro del propio texto de la ayuda. Se informa aparte porque a menudo no coincide con la instalada (la ayuda puede ser más antigua). |
| **Evidencia** | Cada dato usado para clasificar o versionar (nombre de archivo, título interno, entrada de registro…). Se guarda en `manifest.json` para poder auditar el resultado. |

## Seguridad y confidencialidad

La documentación de Navitaire es propiedad de Amadeus. La herramienta está diseñada para que no pueda filtrarse:

- **Solo lectura** sobre las instalaciones: nunca escribe en `C:\Program Files (x86)\Navitaire` y rechaza una carpeta de salida dentro de las raíces de búsqueda.
- **Sin red**: no hace llamadas a Internet, no tiene telemetría.
- **La salida no puede acabar en Git por accidente**: `navhelp convert` se niega a escribir dentro de un repositorio Git salvo en una carpeta ignorada (por ejemplo `.\knowledge`, ya incluida en `.gitignore`).
- **Rutas personales ocultas**: la carpeta de perfil (`C:\Users\<usuario>`) se sustituye por `~` en manifiestos y mensajes. Con `--hide-roots` también se ocultan las raíces.
- **Sin correos internos**: se eliminan de los temas los enlaces `mailto:` de "Send Feedback".
- **Control automático antes de publicar**: `scripts/check_repo_safety.py` bloquea archivos CHM/HHC/HHK/SAZ, ejecutables, Markdown convertido, rutas de perfil, tokens y claves. Se ejecuta en cada commit (hook) y en la integración continua.
- **Extracción segura**: 7-Zip se invoca sin shell y se verifica que ningún archivo extraído quede fuera de la carpeta temporal. Los temporales se eliminan al terminar.
- **Dependencias fijadas** a versiones exactas en `pyproject.toml`.

Reglas para quien use el repositorio:

1. No subas nunca archivos `.chm`, carpetas de salida ni capturas de la documentación.
2. Comparte la documentación convertida solo por los canales internos autorizados.
3. Mantén el repositorio **privado** y da acceso únicamente a personal autorizado de Amadeus.

## Requisitos

| Requisito | Detalle |
| --- | --- |
| Windows 10/11 | La detección de versiones usa el registro y los recursos de versión de Windows. En otros sistemas funciona la conversión, pero la versión quedará como *inferida* o *desconocida*. |
| Python 3.11 o superior | <https://www.python.org/downloads/> (marca *Add python.exe to PATH*). Comprueba con `py --version`. |
| 7-Zip | <https://www.7-zip.org/>. Se busca en `C:\Program Files\7-Zip\7z.exe`, `C:\Program Files (x86)\7-Zip\7z.exe` y en el `PATH`. |
| Git | Para clonar el repositorio. |
| Permisos | Basta con lectura sobre `C:\Program Files (x86)\Navitaire`. No hace falta ser administrador. |
| Espacio | Unos 150 MB para convertir todas las ayudas de una instalación típica. |

## Instalación paso a paso

Abre **PowerShell** y ejecuta:

```powershell
# 1. Clonar (necesitas acceso al repositorio privado)
git clone https://github.com/SergioG977/navitaire-help-exporter.git
Set-Location navitaire-help-exporter

# 2. Crear un entorno virtual aislado
py -m venv .venv
.\.venv\Scripts\Activate.ps1
# Si PowerShell bloquea el script:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 3. Instalar la herramienta
python -m pip install --upgrade pip
python -m pip install .

# 4. Comprobar
navhelp --version
navhelp families
```

Para contribuir al código instala además las herramientas de desarrollo y el hook de seguridad:

```powershell
python -m pip install -e ".[dev]"
.\scripts\install-hooks.ps1
```

Cada vez que abras una nueva ventana de PowerShell, activa el entorno con `.\.venv\Scripts\Activate.ps1` (o usa directamente `.\.venv\Scripts\navhelp.exe`).

## Uso rápido

```powershell
# ¿Qué ayudas hay instaladas? (rápido, no extrae nada)
navhelp scan

# ¿De qué producto y versión es cada una?
navhelp inspect

# Convertir todo a Markdown en %USERPROFILE%\NavitaireHelp y validar el resultado
navhelp convert --validate

# Abrir el catálogo generado
notepad "$HOME\NavitaireHelp\catalog.md"
```

Ejemplo ilustrativo de salida de `navhelp inspect` (versiones ficticias):

```text
FAMILY                         CLASS      INSTALLED VERSIONS           VERSION     HELP STATES FILE
device-manager                 classified 9.2.0.10                     confirmed   -           DeviceManager.chm
gonow                          classified 9.1.0.100                    confirmed   9.1.0       GoNow.chm
skyspeed                       classified 9.3.0.200                    confirmed   9.3.0       SkySpeedHelp.chm
skyspeed                       classified 9.1.0.200, 9.2.0.200         confirmed   8.0.0       SkySpeedHelp.chm
```

La última fila muestra por qué se separan colecciones y versiones: dos versiones instaladas pueden traer exactamente la misma ayuda, y el texto de esa ayuda puede mencionar una versión más antigua.

## Comandos en detalle

Todos los comandos aceptan `--config ARCHIVO` y `-v/--verbose`. `navhelp <comando> --help` muestra la ayuda de cada uno.

### `navhelp families`

Lista las familias reconocidas, su producto y su dominio funcional.

### `navhelp scan`

Busca archivos `.chm` sin abrirlos y muestra cuántos hay, cuántos son distintos y dónde está cada copia.

| Opción | Efecto |
| --- | --- |
| `--root DIR` | Carpeta raíz a recorrer (repetible). Sustituye a la raíz por defecto. |
| `--exclude RUTA` | Carpeta adicional a omitir, relativa a la raíz (repetible). Ej.: `--exclude NewSkies\R4.8`. |
| `--no-default-excludes` | No omitir `ConfigCaptain` ni `NavitaireTE`. |
| `--chm ARCHIVO` | Procesar un CHM concreto en lugar de buscar (repetible). |
| `--hide-roots` | Mostrar `<root>` en lugar de la ruta raíz. |
| `--json` | Salida en JSON. |

### `navhelp inspect`

Además de buscar, lee los metadatos internos de cada CHM (extracción parcial en una carpeta temporal) y muestra familia, estado de clasificación, versiones instaladas, estado de versión y versión mencionada en la ayuda. Con `-v` muestra toda la evidencia; con `--json` devuelve el manifiesto de cada colección.

### `navhelp convert`

Convierte las ayudas encontradas. Acepta las opciones de `scan` y además:

| Opción | Efecto |
| --- | --- |
| `-o, --output DIR` | Carpeta de salida (por defecto `%USERPROFILE%\NavitaireHelp`). |
| `--family ID` | Convertir solo esa familia (repetible). Ej.: `--family gonow --family skyspeed`. |
| `--include-unknown` | Convertir también CHM no reconocidos (familia `unknown`). |
| `--force` | Volver a convertir aunque la colección ya esté al día. |
| `--validate` | Ejecutar `validate` al terminar. |
| `--seven-zip EXE` | Ruta explícita a `7z.exe`. |
| `--allow-unignored-output` | Permitir salida dentro de un repositorio Git no ignorada. **No recomendado.** |

La conversión es **incremental**: si una colección ya existe con la misma versión de la herramienta y las mismas versiones instaladas, se marca `unchanged` y solo se actualiza la lista de ubicaciones. Cada colección se escribe primero en una carpeta temporal `.<hash>.partial` y se publica al terminar, de modo que una interrupción nunca deja una colección a medias.

### `navhelp validate [CARPETA]`

Comprueba una carpeta de salida: manifiestos completos, número de temas correcto, front matter presente y coherente con su colección, catálogo consistente, ausencia de rutas de perfil de usuario. Informa como advertencias los enlaces rotos del origen y las versiones sin confirmar.

### Códigos de salida

| Código | Significado |
| --- | --- |
| `0` | Correcto. |
| `1` | Alguna ayuda falló o la validación encontró errores. |
| `2` | Error de uso o de configuración (7-Zip no encontrado, salida insegura, archivo inexistente…). |

## Configuración

Los valores por defecto funcionan en una instalación estándar. Para cambiarlos, copia el ejemplo (el archivo `navhelp.toml` está ignorado por Git):

```powershell
Copy-Item config\navhelp.example.toml navhelp.toml
navhelp convert --config navhelp.toml
```

```toml
[discovery]
roots = ["C:\\Program Files (x86)\\Navitaire"]
exclude = ["ConfigCaptain", "NavitaireTE"]
follow_links = false

[conversion]
output = "~\\NavitaireHelp"
seven_zip = ""
include_unknown = false
```

Las opciones de línea de comandos tienen prioridad sobre el archivo. Se admiten `~` y variables de entorno (`%USERPROFILE%`).

## Dónde busca y qué excluye

- Raíz por defecto: `C:\Program Files (x86)\Navitaire`.
- Se recorren **recursivamente todas las subcarpetas** (`GovernmentSecurity`, `NAV1`, `NewSkies` y cualquier otra que aparezca).
- Se omiten por completo `ConfigCaptain` y `NavitaireTE` (comparación sin distinguir mayúsculas).
- No se siguen enlaces simbólicos ni *junctions* de NTFS, para no salir de la raíz.
- Las carpetas sin permiso de lectura se informan como advertencia y se continúa.

No hay rutas de instalación codificadas más allá de esta raíz: la herramienta encuentra los CHM dondequiera que estén bajo ella.

## Productos reconocidos

| Familia | Producto | Dominio | Archivo habitual |
| --- | --- | --- | --- |
| `gonow` | GoNow | Check-in, embarque, equipaje y control de salidas | `GoNow.chm` |
| `skyspeed` | SkySpeed Reservation Manager | Reservas, ventas y servicio al pasajero | `SkySpeedHelp.chm` |
| `skyfare` | Fare Manager | Tarifas, reglas tarifarias, mercados y precios | `SkyFareHelp.chm` |
| `skyschedule` | Schedule Manager | Horarios, tramos, rutas y equipos | `SkyScheduleHelp.chm` |
| `newskies-management-console` | New Skies Management Console | Configuración del sistema, roles, permisos y datos de referencia | `Navitaire.NewSkies.UI.Win.SkyManagerHelp.chm` |
| `gss-management-console` | GSS Management Console | Government Security Services: APIS/APPS, reglas y mensajería gubernamental | `Navitaire.GovernmentSecurity.GSSManagementConsole.Help.chm` |
| `device-manager` | Device Manager | Periféricos, escáneres, impresoras, simuladores y logs | `DeviceManager.chm` |
| `ncs-rules` | Rules Management | Plug-in de reglas de Management Console | `Rules.chm` |
| `ncs-currency` | Currency Management | Plug-in de monedas de Management Console | `Currency.chm` |
| `ncs-notification` | Notification Management | Plug-in de notificaciones de Management Console | `Notification.chm` |

Para añadir una familia nueva, agrega una entrada en `src/navitaire_help/families.py` con sus patrones y una prueba en `tests/test_classification_versioning.py`.

## Cómo se identifica el producto

Cada familia define patrones (expresiones regulares) que se comparan con varias señales. Cada señal suma un peso si coincide:

| Señal | Peso | Ejemplo |
| --- | --- | --- |
| Título compilado del CHM (`#SYSTEM`) | 4 | "GoNow Agent Help" |
| Nombre del archivo | 3 | `SkyFareHelp.chm` |
| Título de la página de bienvenida | 2 | "Welcome to Device Manager" |
| Nombre del archivo de contenido (`.hhc`) | 2 | `SkyScheduleHelp.hhc` |
| Carpeta de instalación | 1 | `...\Client Suite\Fare Manager` |

- Con menos de 3 puntos la ayuda queda como `unknown` y no se convierte (salvo `--include-unknown`).
- Si la segunda familia queda a menos de 2 puntos, el estado es `ambiguous` y se muestra la alternativa (`runner_up`).
- La evidencia completa se guarda en `manifest.json → classification.evidence`.

## Cómo se determina la versión

Nunca se usa el nombre del archivo como versión. Las fuentes, de mayor a menor fiabilidad:

1. **Registro de Windows** (solo lectura): entradas de *Uninstall* de Navitaire/Amadeus cuya `InstallLocation` contiene el CHM. Se toma `DisplayVersion` o, si está vacía, la versión del `DisplayName` (caso de *NewSkies Client Suite*).
2. **Ejecutable del producto** junto al CHM o en carpetas superiores dentro de la instalación (`GoNow.exe`, `UI.Win.SkySpeed.exe`, `DeviceManager.exe`…), leyendo `ProductVersion`. Se descarta el sufijo de compilación (`+commit`) y se exige que el fabricante sea Navitaire o Amadeus.
3. **Carpeta con aspecto de versión** (`R9.1`, `9.1.0.100`): solo como versión *inferida*.

| Estado | Significado |
| --- | --- |
| `confirmed` | Registro y/o ejecutable coinciden. |
| `inferred` | Solo hay indicios de la ruta. |
| `conflicting` | Fuentes fiables contradictorias; no se elige ninguna. |
| `unknown` | Sin evidencia. |

La **versión que indica la ayuda** (`document_version`) se extrae aparte del archivo de contenido, el título o la página de bienvenida. Es informativa: una ayuda puede mencionar una versión anterior a la de la aplicación con la que se instala.

## Estructura de la salida

```text
NavitaireHelp/
├── catalog.md                      # tabla de todas las colecciones (empieza aquí)
├── catalog.json                    # lo mismo, para herramientas
└── <familia>/
    └── <hash-12>/                  # una colección = un CHM distinto
        ├── README.md               # resumen: producto, versiones, puntos de entrada
        ├── manifest.json           # metadatos, evidencia, ubicaciones, estadísticas
        ├── toc.md / toc.json       # tabla de contenido original
        ├── topics/                 # un .md por tema, con la estructura interna del CHM
        ├── assets/                 # imágenes y adjuntos referenciados
        ├── indexes/
        │   ├── topics.json         # título, ruta, migas de pan, encabezados, palabras clave
        │   ├── keywords.json       # índice original de palabras clave
        │   └── keywords.md
        └── diagnostics/
            ├── links.json          # enlaces rotos, IDs sin resolver, enlaces a otras ayudas
            └── conversion.json     # colisiones de nombres, temas fallidos, entradas de TOC huérfanas
```

Cada tema empieza con *front matter* YAML:

```yaml
---
title: "<título del tema>"
collection_id: "<familia>-<hash de 12 caracteres>"
family_id: "<familia>"
product: "<producto>"
installed_versions: ["<versión instalada>"]
document_version: "<versión indicada en la ayuda>"
source_chm: "<archivo>.chm"
source_topic: "<ruta interna>.html"
toc_path: ["<capítulo>", "<título del tema>"]
keywords: ["<palabra clave del índice original>"]
---
```

Detalles de la conversión:

- Se elimina la plantilla del visor de ayuda (cabecera, "Send Feedback", pies y copyright repetidos); las secciones plegables con contenido se conservan.
- Los enlaces internos se reescriben como rutas relativas entre archivos `.md`, incluidos los anclajes (`#seccion`). Se toleran diferencias de mayúsculas, espacios, guiones y guiones bajos.
- Los enlaces que no se pueden resolver se convierten en texto y se registran en `diagnostics/links.json`. La mayoría son defectos del CHM original (imágenes no incluidas, IDs de tema que la herramienta de autoría no resolvió).
- Si dos temas producirían el mismo archivo, el segundo se renombra (`__2`) y se registra la colisión.

## Uso con agentes de IA

El repositorio incluye agentes de [Kiro](https://kiro.dev) en `.kiro/agents/`: un especialista por producto y un orquestador que delega en ellos. Para usarlos, convierte la ayuda dentro de la carpeta ignorada `knowledge`:

```powershell
navhelp convert --output .\knowledge --validate
```

La guía completa para crearlos, adaptarlos y probarlos está en [docs/agents.md](docs/agents.md).

## Solución de problemas

| Síntoma | Causa y solución |
| --- | --- |
| `7-Zip not found` | Instala 7-Zip o indica la ruta con `--seven-zip "D:\Tools\7z.exe"`. |
| `Output folder ... is inside the Git repository` | Elige una carpeta fuera del repositorio o usa `.\knowledge`. |
| `Output must not be inside a discovery root` | No escribas dentro de `C:\Program Files (x86)\Navitaire`. |
| `Root not found` | La raíz no existe en este equipo: usa `--root`. |
| `Access denied: ...` | Tu usuario no puede leer esa carpeta; se omite y se continúa. |
| Versión `inferred` o `unknown` | No hay entrada de registro ni ejecutable reconocible. Revisa la evidencia con `navhelp inspect -v`. |
| Familia `unknown` | CHM no reconocido. Revisa con `inspect -v`; conviértelo con `--include-unknown` o añade la familia. |
| Muchos enlaces rotos | Revisa `diagnostics/links.json`; normalmente el destino no existe en el CHM original. |
| Cambios del conversor no aplicados | La colección figura como `unchanged`: usa `--force`. |
| Texto con caracteres extraños | Codificación no declarada en el HTML original; abre una incidencia con el nombre del tema (sin adjuntar su contenido). |

## Desarrollo

```powershell
python -m pip install -e ".[dev]"
.\scripts\install-hooks.ps1          # control de seguridad antes de cada commit
ruff check src tests scripts          # estilo y análisis estático
pytest                                # pruebas (solo datos sintéticos)
python scripts\check_repo_safety.py   # control de seguridad manual
```

Organización del código (`src/navitaire_help/`):

| Módulo | Responsabilidad |
| --- | --- |
| `cli.py` | Comandos y opciones. |
| `config.py` | Valores por defecto y archivo TOML. |
| `discovery.py` | Búsqueda recursiva, exclusiones y hash. |
| `extraction.py` | Invocación segura de 7-Zip. |
| `chm_metadata.py` | Lectura de `#SYSTEM`, `.hhc` y `.hhk`. |
| `families.py` / `classification.py` | Familias conocidas y clasificación por evidencia. |
| `versioning.py` | Registro, recursos de versión de ejecutables y resolución de versión. |
| `markdown.py` | Conversión HTML → Markdown y limpieza de plantilla. |
| `converter.py` | Construcción de una colección: temas, recursos, índices, diagnósticos. |
| `pipeline.py` | Orquestación, manifiestos y catálogo. |
| `validate.py` | Validación de la salida. |
| `safety.py` | Protección de la carpeta de salida y ocultación de rutas. |

Normas:

- Las pruebas usan **solo fixtures sintéticos**. No añadas nunca contenido real de Navitaire, ni siquiera fragmentos.
- Al informar un problema, describe el tema por su nombre de archivo; no pegues su contenido.
- Fija versiones exactas al añadir dependencias.

## Licencia y atribución

Distribuido bajo licencia MIT (ver [LICENSE](LICENSE)). Parte del código deriva de [DTDucas/chm-converter](https://github.com/DTDucas/chm-converter) (MIT); el detalle está en [NOTICE](NOTICE).

La licencia cubre únicamente el código de esta herramienta. La documentación de Navitaire que se procesa sigue siendo propiedad de sus titulares y está sujeta a sus condiciones de uso.
