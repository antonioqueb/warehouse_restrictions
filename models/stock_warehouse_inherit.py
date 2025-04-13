# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    assigned_user_ids = fields.Many2many(
        'res.users',
        'warehouse_user_rel',
        'warehouse_id',
        'user_id',
        string='Assigned Users',
        help="Usuarios que trabajarán exclusivamente con este almacén. "
             "El sistema les creará (o asociará) un grupo y reglas de acceso."
    )

    group_id = fields.Many2one(
        'res.groups',
        string='Warehouse Group',
        copy=False,
        help="Grupo de seguridad asociado a este almacén para restringir datos."
    )

    @api.model
    def create(self, vals):
        """Sobrescribimos create para que, al crear un nuevo almacén,
           se genere o actualice el grupo y reglas de acceso."""
        warehouse = super(StockWarehouse, self).create(vals)
        warehouse._create_or_update_warehouse_group_and_rules()
        return warehouse

    def write(self, vals):
        """Al editar el almacén (cambiar nombre o usuarios asignados),
           actualizamos el grupo y las reglas."""
        res = super(StockWarehouse, self).write(vals)
        for rec in self:
            rec._create_or_update_warehouse_group_and_rules()
        return res

    def _create_or_update_warehouse_group_and_rules(self):
        """Crea o actualiza el grupo (res.groups) ligado a este almacén
           y las reglas de registro (ir.rule) para restringir:
             - stock.picking
             - mrp.production
        """
        self.ensure_one()

        # 1) Crear (o buscar) el grupo de seguridad propio del almacén
        group_name = _("Warehouse: %s") % (self.name or "Unnamed")
        if not self.group_id:
            existing_group = self.env['res.groups'].search([('name', '=', group_name)], limit=1)
            if existing_group:
                self.group_id = existing_group
            else:
                self.group_id = self.env['res.groups'].create({'name': group_name})
        group = self.group_id

        # 2) Sincronizar usuarios asignados -> grupo
        group.users = [(6, 0, self.assigned_user_ids.ids)]

        # 3) Crear / Actualizar la regla de stock.picking
        picking_rule_name = _("Rule: Stock Pickings for %s") % self.name
        picking_rule_domain = "[('picking_type_id.warehouse_id','=',%d)]" % self.id
        picking_model = self.env.ref('stock.model_stock_picking', raise_if_not_found=False)

        if picking_model:
            picking_rule = self.env['ir.rule'].search([
                ('name', '=', picking_rule_name),
                ('model_id', '=', picking_model.id),
            ], limit=1)
            if not picking_rule:
                picking_rule = self.env['ir.rule'].create({
                    'name': picking_rule_name,
                    'model_id': picking_model.id,
                    'domain_force': picking_rule_domain,
                    'groups': [(4, group.id)],  # asignar la regla a este grupo
                })
            else:
                picking_rule.write({
                    'domain_force': picking_rule_domain,
                    'groups': [(4, group.id)],
                })

        # 4) Crear / Actualizar la regla de mrp.production (órdenes de producción)
        mrp_model = self.env['ir.model'].search([('model', '=', 'mrp.production')], limit=1)
        if mrp_model:
            mrp_rule_name = _("Rule: MRP Productions for %s") % self.name
            mrp_rule_domain = "[('picking_type_id.warehouse_id','=',%d)]" % self.id
            mrp_rule = self.env['ir.rule'].search([
                ('name', '=', mrp_rule_name),
                ('model_id', '=', mrp_model.id),
            ], limit=1)
            if not mrp_rule:
                mrp_rule = self.env['ir.rule'].create({
                    'name': mrp_rule_name,
                    'model_id': mrp_model.id,
                    'domain_force': mrp_rule_domain,
                    'groups': [(4, group.id)],
                })
            else:
                mrp_rule.write({
                    'domain_force': mrp_rule_domain,
                    'groups': [(4, group.id)],
                })

        return True
