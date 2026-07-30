<?php

/**
 * ADMIN {SECTION} CONTROLLER
 *
 * CONTROLADOR: Si no declaro el método en este archivo, lo busca en common
 * MODELO ($this->model): Si no declaro el método en el modelo, lo busca en common
 * VISTA ($this->vista): Si no declaro el método en la vista, lo busca en common
 */
class admin_{section}_controller extends admin_layout_controller
{

    private admin_listados_controller $listados;
    private $permisos;
    protected admin_formularios_controller $formularios;

    public function __construct()
    {
        parent::__construct();
        $this->controlar_session();
        $this->permisos = $this->permisos_seccion_accion();
        $this->listados = new admin_listados_controller($this->permisos);
        $this->formularios = new admin_formularios_controller();
    }

    /**
     * Listado principal de {section}
     *
     * @return void
     */
    public function listado(): void
    {
        $titulo = "{Section Title}";
        $contenido = $this->titulo($titulo, "blue");
        $contenido .= $this->subtitulo("Listado de {section}");

        // Add button for new record (opens modal)
        $onclick = "modal_generico_ajax('/" . $_GET["_main"] . "/" . $_GET["_seccion"] . "/agregar/?_ajax=1','','90%');";
        $contenido .= $this->formularios->form_button("agregar_{section}", "Nuevo {section}", $onclick, "btn btn-sm btn-white btn-info btn-bold", "ace-icon glyphicon glyphicon-file bigger-120 blue");

        $filtros = $this->view->filtros();
        $contenido .= $this->listados->filtros_clean("/" . $_GET["_main"] . "/" . $_GET["_seccion"] . "/listado_resultados/", $filtros);

        echo $this->page($contenido);
    }

    /**
     * Datos del listado (AJAX)
     *
     * @return void
     */
    public function listado_resultados(): void
    {
        $datos = $this->model->listado();
        $acciones_listado = $this->listado_acciones_custom($datos);
        $contenido = $this->listados->listado_abm($datos, $acciones_listado);

        echo json_encode(array("status" => 1, "html" => $contenido));
    }

    /**
     * Acciones custom del listado (editar, eliminar)
     *
     * @param array|null $datos
     * @return array|null
     */
    private function listado_acciones_custom($datos = null): ?array
    {
        if (empty($datos)) return null;
        $acciones = array();
        for ($i = 0; $i < count($datos["filas"]); $i++) {
            // Editar
            $acciones["acciones"]["editar"]["label"] = "Editar";
            $onclick = "modal_generico_ajax('/" . $_GET["_main"] . "/" . $_GET["_seccion"] . "/editar/?_ajax=1&id=" . $datos['filas'][$i]["id"] . "','','90%');";
            $acciones["acciones"]["editar"]["filas"][$i] = $this->listados->boton_editar(null, $onclick);

            // Eliminar
            $acciones["acciones"]["eliminar"]["label"] = "Eliminar";
            $href = "javascript:void(0);";
            $onclick_eliminar = 'onclick="modal_generico_ajax(\'/' . $_GET["_main"] . "/" . $_GET["_seccion"] . "/eliminar/?_ajax=1&id=" . $datos['filas'][$i]["id"] . '\',\'\',\'90%\');"';
            $acciones["acciones"]["eliminar"]["filas"][$i] = $this->listados->boton_eliminar($href, $onclick_eliminar);
        }
        return $acciones;
    }

    /**
     * Modal para agregar un nuevo registro
     *
     * @return void
     */
    public function agregar(): void
    {
        if ($_POST["submit"]) {
            $id = $this->model->agregar($_POST);
            if ($id) {
                $this->alertas_push("Registro agregado correctamente", "ok");
                $this->formularios->redirigir_despues_de_guardar();
                return;
            }
            $this->alertas_push("Error al agregar el registro", "error");
            return;
        }

        $titulo = $this->titulo("Agregar {Section}", "white");
        $contenido = $this->view->agregar();

        echo json_encode(array("status" => 1, "body" => $contenido, "title" => $titulo));
    }

    /**
     * Modal para editar un registro existente
     *
     * @return void
     */
    public function editar(): void
    {
        if ($_POST["submit"]) {
            $this->model->editar($this->filtrar_numero_entero($_POST["id"]), $_POST);
            $this->alertas_push("Datos guardados correctamente", "ok");
            $this->formularios->redirigir_despues_de_guardar();
            return;
        }

        $datos = $this->model->obtener($this->filtrar_numero_entero($_REQUEST["id"]));
        $_POST = $this->cargar_post($datos);
        $titulo = $this->titulo("Editar {Section}", "white");
        $contenido = $this->view->editar();

        echo json_encode(array("status" => 1, "body" => $contenido, "title" => $titulo));
    }

    /**
     * Modal de confirmación para eliminar un registro
     *
     * @return void
     */
    public function eliminar(): void
    {
        if ($_POST["submit"]) {
            $this->model->eliminar($this->filtrar_numero_entero($_POST["id"]));
            $this->alertas_push("Registro eliminado correctamente", "ok");
            $this->formularios->redirigir_despues_de_guardar();
            return;
        }

        $titulo = $this->titulo("Eliminar {Section}", "white");
        $contenido = $this->view->eliminar();

        echo json_encode(array("status" => 1, "body" => $contenido, "title" => $titulo));
    }
}
