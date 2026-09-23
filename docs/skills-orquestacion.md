# Orquestación de Skills - JDownloader Clone

**Última actualización**: 23 de septiembre de 2026

## Visión General

Los **skills** son extensiones especializadas del agente Copilot que proporcionan funcionalidad específica para tareas recurrentes del proyecto. Se invocan automáticamente cuando el usuario hace una pregunta o solicitud que cae dentro de su ámbito de acción.

**Ubicación**: `.github/skills/`  
**Formato**: Cada skill es una carpeta con un archivo `SKILL.md` que define metadatos y comportamiento.

---

## Skills Disponibles

### 1. **commit-message** 🔄
**Ubicación**: `.github/skills/commit-message/SKILL.md`

**Descripción**:  
Generador de mensajes de commit siguiendo convenciones **Conventional Commits** del proyecto. Asegura consistencia en el historial de cambios y facilita la generación automática de changelogs.

**Cuándo usarlo**:
- Cuando vayas a hacer un commit
- Quieras redactar un mensaje de commit siguiendo estándares
- Necesites describir un cambio para Git
- Preguntes cómo formular un commit correctamente

**Argumento esperado**:  
Descripción breve del cambio que vas a commitear.

**Ejemplo de invocación**:
```
@copilot, usa la skill commit-message para: "Agregué validación en el plugin de YouTube"
```

**Salida esperada**:  
Mensaje estructurado:
```
feat(backend): agregar validación en plugin YouTube

Valida URLs antes de iniciar descarga. Detecta URLs inválidas
y retorna error 400 con mensaje descriptivo.

Closes #45
```

**Tipos de commit soportados**:
| Tipo | Uso |
|------|-----|
| `feat` | Nueva funcionalidad |
| `fix` | Corrección de bug |
| `docs` | Documentación |
| `refactor` | Reestructuración |
| `test` | Tests |
| `chore` | Mantenimiento |
| `style` | Formato |
| `perf` | Rendimiento |
| `ci` | Pipelines/CI |
| `revert` | Revierte commit |

**Formato**:
```
<tipo>(ámbito): resumen imperativo ≤50 chars

[cuerpo opcional explicando EL PORQUÉ — ≤72 chars/línea]

[Closes #issue / Refs #123]
```

**Restricciones**:
- Resumen: máximo 50 caracteres (límite duro: 72)
- Usar modo imperativo: "agregar", "corregir", "refactor" (no "agregado", "se corrigió")
- Cuerpo opcional pero recomendado si el cambio no es obvio
- El cuerpo explica el **PORQUÉ**, no el **CÓMO** (el diff ya muestra el cómo)

---

## Cómo Crear un Nuevo Skill

Si necesitas agregar un nuevo skill al proyecto, sigue este procedimiento:

### 1. Crear la estructura

```
.github/skills/
└── mi-skill/
    └── SKILL.md
```

### 2. Frontmatter YAML

El archivo `SKILL.md` debe comenzar con:

```yaml
---
name: mi-skill
description: 'Descripción breve de qué hace este skill'
argument-hint: 'Qué argumento/contexto espera recibir'
---
```

### 3. Contenido

Documenta:
- **Qué hace** el skill
- **Cuándo invocarlo** (triggers)
- **Qué argumento recibe**
- **Ejemplos de uso**
- **Restricciones o precondiciones**

### 4. Registrar en copilot-instructions.md

Añade una referencia en la sección de Skills de `copilot-instructions.md`.

---

## Invocación de Skills

### Desde Chat de Copilot

Menciona el skill de forma natural:

```
Usa la skill commit-message para: Agregué soporte para descargas de Vimeo
```

O más directamente:

```
#commit-message: Agregué soporte para descargas de Vimeo
```

### Automática

Algunos skills se invocan automáticamente si detectan palabras clave:

- **commit-message**: Se invoca cuando mencionas "commit", "mensaje de commit", "hacer un commit", etc.

---

## Referencia Rápida

| Skill | Ubicación | Uso | Argumento |
|-------|-----------|-----|-----------|
| **commit-message** | `.github/skills/commit-message/SKILL.md` | Generar mensajes de commit | Descripción del cambio |

---

## Mejores Prácticas

1. **Mantén los skills enfocados**  
   Cada skill resuelve un problema específico y bien definido.

2. **Documenta claramente**  
   Incluye ejemplos reales y casos de uso en el `SKILL.md`.

3. **Valida argumentos**  
   El skill debe validar qué recibe y dar feedback claro si falta información.

4. **Reutilizable**  
   Diseña skills que puedan aplicarse a múltiples contextos del proyecto.

5. **Actualiza este documento**  
   Cuando crees un nuevo skill, añádelo a esta guía y a `copilot-instructions.md`.

---

## Troubleshooting

### El skill no se invoca

**Causas comunes**:
- El archivo `SKILL.md` tiene errores de sintaxis YAML
- El `name:` en frontmatter no coincide con la carpeta
- Los tipos de disparo (keywords) no están configurados

**Solución**:
- Verifica el formato YAML en `.github/skills/[skill-name]/SKILL.md`
- Consulta la skill de `agent-customization` para debugging

### El skill recibe argumentos incorrectos

**Solución**:
- Revisa el `argument-hint` en el frontmatter
- Proporciona contexto más específico en tu solicitud a Copilot
- Añade ejemplos en el cuerpo del `SKILL.md`

---

## Véase También

- [copilot-instructions.md](../copilot-instructions.md) — Guía general del proyecto para Copilot
- [.github/skills/](../.github/skills/) — Ubicación de los skills
- [Conventional Commits](https://www.conventionalcommits.org/) — Estándar de mensajes de commit
