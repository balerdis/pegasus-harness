<?php

class admin_{section}_controller extends admin_layout_controller
{
    private $listados;
    private $permisos;
    protected $formularios;

    public function __construct()
    {
        parent::__construct();
        $this->controlar_session();
        $this->permisos = $this->permisos_seccion_accion();
        $this->listados = new admin_listados_controller($this->permisos);
        $this->formularios = new admin_formularios_controller();
    }

    public function listado()
    {
        $contenido = $this->titulo("{Section Title}", "blue");
        $contenido .= $this->subtitulo("Listado de {section}");
        $contenido .= $this->listados->filtros_clean("/" . $_GET["_main"] . "/" . $_GET["_seccion"] . "/listado_resultados/", $this->view->filtros());

        echo $this->page($contenido);
    }

    public function listado_resultados()
    {
        $datos = $this->model->listado();
        $acciones = $this->listado_acciones_custom($datos);
        $html = $this->listados->listado_abm($datos, $acciones);

        echo json_encode(array("status" => 1, "html" => $html));
    }

    private function listado_acciones_custom($datos = null)
    {
        if (empty($datos)) return null;

        $acciones = array();
        for ($i = 0; $i < count($datos["filas"]); $i++) {
            $id = $datos["filas"][$i]["id"];
            $onclick = "modal_generico_ajax('/" . $_GET["_main"] . "/" . $_GET["_seccion"] . "/editar/?_ajax=1&id=" . $id . "','','90%');";
            $acciones["acciones"]["editar"]["label"] = "Editar";
            $acciones["acciones"]["editar"]["filas"][$i] = $this->listados->boton_editar(null, $onclick);
        }

        return $acciones;
    }

    public function editar()
    {
        if ($_POST["submit"]) {
            $this->model->editar($this->filtrar_numero_entero($_POST["id"]), $_POST);
            $this->alertas_push("Datos guardados correctamente", "ok");
            $this->formularios->redirigir_despues_de_guardar();
            return;
        }

        $datos = $this->model->obtener($this->filtrar_numero_entero($_REQUEST["id"]));
        $_POST = $this->cargar_post($datos);
        $contenido = $this->view->editar();
        $titulo = $this->titulo("Editar {Section Title}", "white");

        echo json_encode(array("status" => 1, "body" => $contenido, "title" => $titulo));
    }
}
