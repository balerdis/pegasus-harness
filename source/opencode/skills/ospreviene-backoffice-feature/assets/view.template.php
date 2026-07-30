<?php

/**
 * ADMIN {SECTION} VIEW
 *
 * Vista de {section}.
 * Contiene todo el HTML renderizado.
 */
class admin_{section}_view extends admin_layout_view
{

    public function __construct()
    {
        parent::__construct();
    }

    /**
     * Filtros del listado
     *
     * @return string HTML
     */
    public function filtros(): string
    {
        ob_start(); ?>

        <div class="col-xs-12 col-sm-6">
            <?= $this->formularios->form_input("campo1", "Campo 1"); ?>
        </div>
        <div class="col-xs-12 col-sm-6">
            <?= $this->formularios->form_select("campo2", "Campo 2", "{related_table}", "Seleccione"); ?>
        </div>

        <?php return ob_get_clean();
    }

    /**
     * Formulario para agregar
     *
     * @return string HTML
     */
    public function agregar(): string
    {
        ob_start(); ?>
        <form class="form-horizontal" name="agregar" id="agregar" role="form" method="post"
              action="<?= $_SERVER["REQUEST_URI"] ?>">

            <div class="col-xs-12 col-sm-6">
                <?= $this->formularios->form_input("campo1", "Campo 1"); ?>
            </div>
            <div class="col-xs-12 col-sm-6">
                <?= $this->formularios->form_input("campo2", "Campo 2"); ?>
            </div>

            <div class="clearfix form-actions">
                <div class="col-md-12 margin-top-10px">
                    <?= $this->formularios->form_submit("agregar", "Guardar"); ?>
                    <?= $this->formularios->form_button("cancelar", "Cancelar", "cerrar_modal_generico();", "btn btn-sm btn-danger", "ace-icon fa fa-times red2"); ?>
                </div>
            </div>
        </form>
        <?php return ob_get_clean();
    }

    /**
     * Formulario para editar
     *
     * @return string HTML
     */
    public function editar(): string
    {
        ob_start(); ?>
        <form class="form-horizontal" name="editar" id="editar" role="form" method="post"
              action="<?= $_SERVER["REQUEST_URI"] ?>">

            <input type="hidden" name="id" value="<?= $_REQUEST["id"] ?>"/>

            <div class="col-xs-12 col-sm-6">
                <?= $this->formularios->form_input("campo1", "Campo 1"); ?>
            </div>
            <div class="col-xs-12 col-sm-6">
                <?= $this->formularios->form_input("campo2", "Campo 2"); ?>
            </div>

            <div class="clearfix form-actions">
                <div class="col-md-12 margin-top-10px">
                    <?= $this->formularios->form_submit("editar", "Guardar"); ?>
                    <?= $this->formularios->form_button("cancelar", "Cancelar", "cerrar_modal_generico();", "btn btn-sm btn-danger", "ace-icon fa fa-times red2"); ?>
                </div>
            </div>
        </form>
        <?php return ob_get_clean();
    }

    /**
     * Confirmación de eliminación
     *
     * @return string HTML
     */
    public function eliminar(): string
    {
        ob_start(); ?>
        <form class="form-horizontal" name="eliminar" id="eliminar" role="form" method="post"
              action="<?= $_SERVER["REQUEST_URI"] ?>">
            <div class="modal-body">
                <button type="button" class="bootbox-close-button close" data-dismiss="modal" aria-hidden="true"
                        style="margin-top: -10px;">×
                </button>
                <div class="bootbox-body">¿Está seguro que desea eliminar el registro?</div>
            </div>
            <input type="hidden" name="id" value="<?= $_REQUEST["id"] ?>"/>
            <div class="clearfix form-actions">
                <div class="col-md-12 margin-top-10px">
                    <?= $this->formularios->form_submit("eliminar", "Eliminar"); ?>
                    <?= $this->formularios->form_button("cancelar", "Cancelar", "cerrar_modal_generico();", "btn btn-sm btn-danger", "ace-icon fa fa-times red2"); ?>
                </div>
            </div>
        </form>
        <?php return ob_get_clean();
    }
}
