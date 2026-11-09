# ODOO-PARSER (Importador Inteligente de Datos)

Módulo nativo de **Odoo 19** que transforma archivos crudos (Excel / CSV) en registros limpios de Odoo mediante un pipeline ETL asistido por IA. Proyecto Integrador 2 – EAFIT.

---

## Enlace de despliegue

> **URL de la aplicación desplegada:** 

---

## 1. Información de la aplicación

### Problema
La homologación de datos de clientes es una tarea manual. Al migrar a Odoo o recibir bases de terceros (distribuidores, ferias, cámaras de comercio, sistemas legados), cada archivo trae encabezados distintos: `NIT`, `Nit Cliente`, `Identificación`, `Doc.` o `RUT` significan lo mismo, pero Odoo espera el campo `vat`. El analista debe interpretar cada columna, renombrarla a mano y ejecutar el importador nativo, que falla en la primera inconsistencia, obligando a repetir el ciclo (entre 2 y 5 horas por archivo).

### Solución
**Importador Inteligente de Datos** (`smart_data_importer`) reconoce automáticamente a qué campo de Odoo corresponde cada columna, limpia y valida los valores, detecta duplicados y muestra todo al usuario **antes** de escribir en la base de datos (*human-in-the-loop*: nunca se escribe sin confirmación explícita).

### Funcionalidades principales
- Lectura de **CSV, XLSX/XLSM y XLS** con detección automática de codificación, delimitador, fila de encabezado y hojas (omite hojas de instrucciones o de "posibles valores").
- **Mapeo automático de columnas** en cascada con puntaje de confianza y justificación.
- **Plantillas reutilizables**: si los encabezados coinciden con una importación previa, el mapeo se aplica directamente.
- **Reglas de limpieza** (email, teléfono, documento/VAT, etc.).
- **Detección de duplicados** con criterio (VAT, email, VAT o email, automático) y política (actualizar, omitir, crear).
- **Vista previa** con los datos originales junto a los mapeados, y corrección manual de columnas y valores.
- **Memoria de correcciones** de valores para futuras importaciones.
- **Explicación de errores** por fila y resumen de errores (pre-validación e importación).
- **Procesamiento por lotes en cola** para grandes volúmenes, con seguimiento del progreso.
- Soporta varios modelos destino de Odoo (por ejemplo `res.partner`, cuentas, impuestos, productos).

---

## 2. ¿Cómo funciona?

```
Archivo (CSV/Excel)
      │
      ▼
 1. Lectura y detección (encoding, delimitador, encabezados, hoja)
      │
      ▼
 2. ¿Existe plantilla con la misma firma de encabezados? ── sí ──► aplica mapeo guardado
      │ no
      ▼
 3. Mapeo en cascada (solo lo que queda sin resolver pasa al siguiente nivel)
      ├─ Nivel 1 · Hash      → diccionario de sinónimos ("NIT" → vat)
      ├─ Nivel 2 · Fuzzy     → similitud de texto con RapidFuzz (tildes, mayúsculas, typos)
      └─ Nivel 3 · LLM       → análisis semántico con nombre de columna + valores de muestra
      │
      ▼
 4. Revisión humana: vista previa, confianza (verde→rojo), correcciones
      │
      ▼
 5. Limpieza + validación + deduplicación
      │
      ▼
 6. Importación por lotes en cola ──► registros en Odoo
```

**Estados de una sesión de importación:** `Borrador → Analizando → Mapeado → En cola → Procesando → Terminado / Error`.

### Proveedores de IA soportados (configurable en Ajustes)
Anthropic (Claude), OpenAI, DeepSeek, Google Gemini y cualquier endpoint compatible con OpenAI (Ollama, Groq, OpenRouter…). Incluye prueba de conexión y umbral de similitud difuso configurable.

> Los datos de clientes usados en pruebas se anonimizan; no se envían datos personales reales al proveedor de LLM.

---

## 3. Tecnologías y con qué está desarrollado

| Capa | Tecnología |
|---|---|
| Plataforma | **Odoo 19** (framework ORM, vistas XML, seguridad, cron, colas) |
| Backend | **Python 3** |
| Frontend | **JavaScript (OWL)** + plantillas **XML** (tabla de vista previa) |
| Lectura de archivos | `pandas`, `openpyxl`, `chardet` |
| Mapeo difuso | `rapidfuzz` |
| Integración con IA | `requests` (APIs REST de Anthropic, OpenAI, DeepSeek, Gemini y compatibles) |
| Base de datos | **PostgreSQL** (vía Odoo) |
| Pruebas | Tests de Odoo (`tests/`) y `pytest` para pruebas unitarias |
| Calidad de código | `pylint-odoo` / `ruff` |
| Despliegue | Odoo.sh / entorno Odoo 19 |
| Control de versiones | Git + GitHub (Conventional Commits) |

**Dependencias Python** (`requirements.txt`): `rapidfuzz`, `pandas`, `openpyxl`, `chardet`, `requests`.

---

## 4. Estructura del repositorio

```
ODOO-PARSER-0-V3/
├── smart_data_importer/       # Módulo principal: importador inteligente
│   ├── models/                # Sesiones, plantillas, mapeos, errores, reglas, memoria
│   │   └── mixins/            # Archivo, progreso, firma y deduplicación
│   ├── services/              # Lógica: file_reader, mapper_hash/fuzzy/llm, orchestrator,
│   │                          # cleansing_engine, deduplication_engine, error_explainer...
│   ├── data/                  # Registro de sinónimos, reglas de limpieza, config, secuencias
│   ├── views/                 # Vistas y menús
│   ├── static/src/            # Componente JS/XML de vista previa
│   ├── security/              # Grupos y permisos
│   ├── migrations/            # Migraciones de datos
│   └── tests/                 # Pruebas de Odoo y unitarias (pytest)
├── pgm_osaka_loyalty/         # Puntos y vencimientos de lealtad (Osaka)
├── pgm_extended_fields_osaka/ # Extensión de campos de tarjetas de lealtad
├── pgm_wms_progress/          # Progreso y velocidad WMS (PDA)
├── rules/                     # Reglas y guías de desarrollo Odoo
├── sprint.md                  # Documentación del Sprint 0
└── requirements.txt
```

> Los módulos `pgm_*` son módulos complementarios del repositorio; el núcleo del proyecto es `smart_data_importer`.

---

## 5. Instalación

1. Clonar el repositorio dentro de la ruta de *addons* de Odoo 19:
   ```bash
   git clone https://github.com/Eafit-Par-0/ODOO-PARSER-0-V3.git
   ```
2. Instalar las dependencias Python:
   ```bash
   pip install -r requirements.txt
   ```
3. Agregar la carpeta al `addons_path` en `odoo.conf` y reiniciar Odoo.
4. Activar el modo desarrollador → *Aplicaciones* → **Actualizar lista de aplicaciones**.
5. Instalar **Importador Inteligente de Datos**.
6. En *Ajustes* configurar el proveedor de IA, el modelo y la API key.

> En **Odoo.sh** basta con subir el código al repositorio: `requirements.txt` instala las dependencias automáticamente.

---

## 6. Equipo

Samuel Echeverri · Sara Vasquez · Adyuer Ojeda · Tomás Gañán · Victor Infante · Samuel Serpa

**Product Owner:** Jesús Alberto Pérez de la Hoz (Odoo)

## Licencia

LGPL-3

