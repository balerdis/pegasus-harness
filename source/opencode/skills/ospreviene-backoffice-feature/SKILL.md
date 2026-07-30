---
name: ospreviene-backoffice-feature
description: >
  Creates a new admin section (CRUD) in the Ospreviene backoffice following Leannec conventions.
  Trigger: When creating a new admin feature, section, or CRUD in the backoffice.
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## When to Use

- Creating a new admin section with CRUD operations
- Adding a new entity to the backoffice
- Creating list, add, edit, delete functionality for any domain entity

## Critical Patterns

### Inheritance Chain (NON-NEGOTIABLE)

```
Generica → CommonControllers → common_layout_controller → admin_layout_controller → admin_{section}_controller
Generica → CommonModels → common_layout_model → admin_layout_model → admin_{section}_model
Generica → CommonViews → common_layout_view → admin_layout_view → admin_{section}_view
```

**NEVER** extend `common_*` directly from `custom/`. Always go through `admin_layout_*`.

### File Structure

```
custom/admin/secciones/admin_{section}/
├── admin_{section}_controller.php    ← class admin_{section}_controller extends admin_layout_controller
├── admin_{section}_model.php         ← class admin_{section}_model extends admin_layout_model
└── admin_{section}_view.php          ← class admin_{section}_view extends admin_layout_view
```

### Naming Convention (STRICT)

| Element | Pattern | Example |
|---------|---------|---------|
| Directory | `admin_{section}/` | `admin_diagnosticos/` |
| Controller file | `admin_{section}_controller.php` | `admin_diagnosticos_controller.php` |
| Model file | `admin_{section}_model.php` | `admin_diagnosticos_model.php` |
| View file | `admin_{section}_view.php` | `admin_diagnosticos_view.php` |
| Controller class | `admin_{section}_controller` | `admin_diagnosticos_controller` |
| Model class | `admin_{section}_model` | `admin_diagnosticos_model` |
| View class | `admin_{section}_view` | `admin_diagnosticos_view` |

### Controller Constructor Pattern

```php
public function __construct()
{
    parent::__construct();
    $this->controlar_session();
    $this->permisos = $this->permisos_seccion_accion();
    $this->listados = new admin_listados_controller($this->permisos);
    $this->formularios = new admin_formularios_controller();
}
```

### Standard CRUD Methods

| Method | URL | Purpose |
|--------|-----|---------|
| `listado()` | `/{section}/listado/` | Display list page with filters |
| `listado_resultados()` | AJAX | Return list data as JSON `{status: 1, html: "..."}` |
| `agregar()` | `/{section}/agregar/?_ajax=1` | Add form (modal) |
| `editar()` | `/{section}/editar/?_ajax=1&id=X` | Edit form (modal) |
| `eliminar()` | `/{section}/eliminar/?_ajax=1&id=X` | Delete confirmation (modal) |

### Model `listado()` Pattern

Must return `$this->mysql->listado($query, $columnas)` with this structure:

```php
$columnas["campo"] = "Label visible";   // column labels
$orden = $this->mysql->mysql_query_orden($columnas_orden);
$limit = $this->mysql->mysql_query_limit();
$query = "SELECT ... FROM tabla WHERE habilitado AND feliminado IS NULL $orden $limit";
return $this->mysql->listado($query, $columnas);
```

### View Pattern

Views use `ob_start()` / `ob_get_clean()` and the `$this->formularios` helper:

```php
public function editar() {
    ob_start(); ?>
    <form class="form-horizontal" method="post" action="<?= $_SERVER["REQUEST_URI"] ?>">
        <?= $this->formularios->form_input("campo", "Label"); ?>
        <div class="clearfix form-actions">
            <?= $this->formularios->form_submit("guardar", "Guardar"); ?>
            <?= $this->formularios->form_button("cancelar", "Cancelar", "cerrar_modal_generico();", "btn btn-sm btn-danger", "ace-icon fa fa-times red2"); ?>
        </div>
    </form>
    <?php return ob_get_clean();
}
```

### Modal Pattern

Forms open in modals via AJAX. Return JSON from controller:

```php
// In controller::agregar() or editar():
$contenido = $this->view->agregar();
echo json_encode(array("status" => 1, "body" => $contenido, "title" => "Titulo"));
```

### List Actions Pattern

```php
$acciones["acciones"]["editar"]["label"] = "Editar";
$acciones["acciones"]["editar"]["filas"][$i] = $this->listados->boton_editar(null, $onclick);
$acciones["acciones"]["eliminar"]["label"] = "Eliminar";
$acciones["acciones"]["eliminar"]["filas"][$i] = $this->listados->boton_eliminar($href, $onclick_eliminar);
```

### Permissions

Every section MUST have:
1. `$this->controlar_session()` — validates user session
2. `$this->permisos = $this->permisos_seccion_accion()` — checks section permissions

### Alert Pattern

```php
$this->alertas_push("Mensaje de exito", "ok");
$this->alertas_push("Mensaje de error", "error");
```

### Redirect After Save

```php
$this->formularios->redirigir_despues_de_guardar();
```

## Code Examples

See [assets/controller.template.php](assets/controller.template.php) for full controller template.
See [assets/model.template.php](assets/model.template.php) for full model template.
See [assets/view.template.php](assets/view.template.php) for full view template.

## Form Helpers Reference

| Helper | Usage |
|--------|-------|
| `form_input(name, label)` | Text input |
| `form_textarea(name, label)` | Textarea |
| `form_select(name, label, table, placeholder)` | Select from DB table |
| `form_checkbox(name, label)` | Checkbox |
| `form_datepicker(name, label)` | Date picker |
| `form_submit(name, label)` | Submit button |
| `form_button(name, label, onclick, class, icon)` | Custom button |

## Commands

```bash
# Create section directory
mkdir -p custom/admin/secciones/admin_{section}

# Create the three files
touch custom/admin/secciones/admin_{section}/admin_{section}_controller.php
touch custom/admin/secciones/admin_{section}/admin_{section}_model.php
touch custom/admin/secciones/admin_{section}/admin_{section}_view.php
```

## Resources

- **Templates**: See [assets/](assets/) for MVC templates
- **Architecture**: See `AGENTS.md` in project root for full architecture rules
- **Example sections**: `custom/admin/secciones/admin_diagnosticos/` (simple CRUD)
