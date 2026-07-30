<?php

/**
 * ADMIN {SECTION} MODEL
 *
 * Modelo de datos para {section}.
 * Contiene toda la lógica de acceso a datos.
 */
class admin_{section}_model extends admin_layout_model
{
    // Table name for this entity
    private string $tabla = "{table_name}";

    public function __construct()
    {
        parent::__construct();
    }

    /**
     * Listado de registros para el grid
     *
     * @return array Estructura: ["columnas" => [...], "filas" => [...], "total" => int]
     */
    public function listado(): array
    {
        // Column labels for the grid
        $columnas["campo1"] = "Label Campo 1";
        $columnas["campo2"] = "Label Campo 2";

        // Column labels for ordering
        $columnas_orden["campo1"] = "Label Campo 1";

        // Where clause (filters)
        $where = "";
        // if ($_REQUEST["filtro"]) {
        //     $where = "AND t.campo = " . $this->mysql->escape($_REQUEST["filtro"]);
        // }

        // Ordering
        $orden = $this->mysql->mysql_query_orden($columnas_orden);
        if (!$orden) {
            $orden = "ORDER BY t.campo1";
        }

        // Pagination
        $limit = $this->mysql->mysql_query_limit();

        $query = "
            SELECT
                t.id
                ,t.campo1
                ,t.campo2
            FROM {$this->tabla} t
            WHERE
                t.habilitado
                AND t.feliminado IS NULL
                {$where}
            {$orden}
            {$limit}";

        return $this->mysql->listado($query, $columnas);
    }

    /**
     * Obtener un registro por ID
     *
     * @param int $id
     * @return array|null
     */
    public function obtener(int $id): ?array
    {
        $query = "
            SELECT
                t.id
                ,t.campo1
                ,t.campo2
            FROM {$this->tabla} t
            WHERE
                t.habilitado
                AND t.feliminado IS NULL
                AND t.id = {$id}";

        $datos = $this->mysql->consulta($query);
        return $datos[0] ?? null;
    }

    /**
     * Agregar un nuevo registro
     *
     * @param array $post Datos del formulario ($_POST)
     * @return int|false ID del registro insertado o false en error
     */
    public function agregar(array $post)
    {
        $datos["campo1"] = $post["campo1"];
        $datos["campo2"] = $post["campo2"];
        $datos["habilitado"] = 1;

        return $this->mysql->form_agregar($this->tabla, $datos);
    }

    /**
     * Editar un registro existente
     *
     * @param int $id ID del registro
     * @param array $post Datos del formulario ($_POST)
     * @return int|bool Filas afectadas
     */
    public function editar(int $id, array $post)
    {
        $datos["campo1"] = $post["campo1"];
        $datos["campo2"] = $post["campo2"];
        $datos["fmodificacion"] = "now()";

        return $this->mysql->form_modificar($this->tabla, $datos, $id);
    }

    /**
     * Eliminar un registro (soft delete)
     *
     * @param int $id ID del registro
     * @return int|bool Filas afectadas
     */
    public function eliminar(int $id)
    {
        $datos["habilitado"] = null;
        $datos["feliminado"] = "now()";
        $datos["fmodificacion"] = "now()";

        return $this->mysql->form_modificar($this->tabla, $datos, $id);
    }
}
