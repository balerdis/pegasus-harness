<?php

class admin_{section}_model extends admin_layout_model
{
    private $tabla = "{table_name}";

    public function __construct()
    {
        parent::__construct();
    }

    public function listado()
    {
        $columnas["id"] = "ID";
        $columnas["nombre"] = "Nombre";

        $columnas_orden["id"] = "ID";
        $columnas_orden["nombre"] = "Nombre";

        $where = "";
        $orden = $this->mysql->mysql_query_orden($columnas_orden);
        if (!$orden) $orden = "ORDER BY t.id DESC";
        $limit = $this->mysql->mysql_query_limit();

        $query = "
            SELECT
                t.id
                ,t.nombre
            FROM {$this->tabla} t
            WHERE
                t.habilitado
                AND t.feliminado IS NULL
                {$where}
            {$orden}
            {$limit}";

        return $this->mysql->listado($query, $columnas);
    }

    public function obtener($id)
    {
        $query = "
            SELECT
                t.*
            FROM {$this->tabla} t
            WHERE
                t.habilitado
                AND t.feliminado IS NULL
                AND t.id = " . (int) $id;

        $datos = $this->mysql->consulta($query);
        return isset($datos[0]) ? $datos[0] : null;
    }

    public function editar($id, $post)
    {
        $datos["nombre"] = $post["nombre"];
        $datos["fmodificacion"] = "now()";

        return $this->mysql->form_modificar($this->tabla, $datos, $id);
    }
}
