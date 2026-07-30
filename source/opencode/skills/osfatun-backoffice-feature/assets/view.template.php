<?php

class admin_{section}_view extends admin_layout_view
{
    public function __construct()
    {
        parent::__construct();
    }

    public function filtros()
    {
        ob_start(); ?>
        <div class="col-xs-12 col-sm-6">
            <?= $this->formularios->form_input("nombre", "Nombre"); ?>
        </div>
        <?php return ob_get_clean();
    }

    public function editar()
    {
        ob_start(); ?>
        <form class="form-horizontal" name="editar" id="editar" role="form" method="post" action="<?= $_SERVER["REQUEST_URI"] ?>">
            <input type="hidden" name="id" value="<?= $_REQUEST["id"] ?>" />

            <div class="col-xs-12 col-sm-6">
                <?= $this->formularios->form_input("nombre", "Nombre"); ?>
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
}
