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
        help="Usuarios que trabajarán exclusivamente con este/estos almacén(es)."
    )

    group_id = fields.Many2one(
        'res.groups',
        string='Warehouse Group',
        copy=False,
        help="Grupo de seguridad asociado a este almacén para restringir datos."
    )

    manu_type_id = fields.Many2one(
        'stock.picking.type',
        string='Manufacturing Operation Type',
        help="Tipo de operación usado para las órdenes de producción en este almacén."
    )

    @api.model
    def create(self, vals):
        warehouse = super(StockWarehouse, self).create(vals)
        warehouse._create_or_update_warehouse_group_and_rules()
        return warehouse

    def write(self, vals):
        res = super(StockWarehouse, self).write(vals)
        for rec in self:
            rec._create_or_update_warehouse_group_and_rules()
        return res

    def _create_or_update_warehouse_group_and_rules(self):
        """
        Crea o actualiza el grupo (res.groups) ligado a este almacén
        y las reglas de registro (ir.rule) para restringir datos
        a este almacén (con ubicaciones globales incluidas).
        """
        self.ensure_one()

        # 1) Grupo
        group_name = _("Warehouse: %s") % (self.name or "Unnamed")
        if not self.group_id:
            existing_group = self.env['res.groups'].search([('name', '=', group_name)], limit=1)
            if existing_group:
                self.group_id = existing_group
            else:
                self.group_id = self.env['res.groups'].create({'name': group_name})
        group = self.group_id

        # 2) Asignar usuarios
        group.users = [(6, 0, self.assigned_user_ids.ids)]

        def _create_or_update_rule(rule_name, model_xmlid, domain_force):
            if not model_xmlid:
                return
            model = self.env.ref(model_xmlid, raise_if_not_found=False)
            if not model:
                return
            existing_rule = self.env['ir.rule'].search([
                ('name', '=', rule_name),
                ('model_id', '=', model.id),
            ], limit=1)
            if not existing_rule:
                self.env['ir.rule'].create({
                    'name': rule_name,
                    'model_id': model.id,
                    'domain_force': domain_force,
                    'groups': [(4, group.id)],
                })
            else:
                existing_rule.write({
                    'domain_force': domain_force,
                    'groups': [(4, group.id)],
                })

        # Reglas
        picking_rule_name = _("Rule: Stock Pickings for %s") % self.name
        picking_rule_domain = "[('picking_type_id.warehouse_id','=', %d)]" % self.id
        _create_or_update_rule(picking_rule_name, 'stock.model_stock_picking', picking_rule_domain)

        mrp_rule_name = _("Rule: MRP Productions for %s") % self.name
        mrp_rule_domain = "[('picking_type_id.warehouse_id','=', %d)]" % self.id
        _create_or_update_rule(mrp_rule_name, 'mrp.model_mrp_production', mrp_rule_domain)

        picking_type_rule_name = _("Rule: Picking Types for %s") % self.name
        picking_type_rule_domain = "[('warehouse_id','=', %d)]" % self.id
        _create_or_update_rule(picking_type_rule_name, 'stock.model_stock_picking_type', picking_type_rule_domain)

        location_rule_name = _("Rule: Locations for %s") % self.name
        location_rule_domain = (
                "['|', "
                " ('id','child_of', %d), "
                " ('usage','in',['supplier','customer','production','inventory','view','transit','internal'])]"
            ) % (self.view_location_id.id or 0)
        _create_or_update_rule(location_rule_name, 'stock.model_stock_location', location_rule_domain)

        quant_rule_name = _("Rule: Quants for %s") % self.name
        quant_rule_domain = "[('location_id','child_of', %d)]" % (self.lot_stock_id.id or 0)
        _create_or_update_rule(quant_rule_name, 'stock.model_stock_quant', quant_rule_domain)

        move_rule_name = _("Rule: Stock Moves for %s") % self.name
        move_rule_domain = (
            "['|','|','|',"
            " ('location_id','child_of', %d),"
            " ('location_dest_id','child_of', %d),"
            " ('location_id.usage','in',['supplier','customer','production','inventory','transit','view']),"
            " ('location_dest_id.usage','in',['supplier','customer','production','inventory','transit','view'])"
            "]"
        ) % (self.lot_stock_id.id or 0, self.lot_stock_id.id or 0)
        _create_or_update_rule(move_rule_name, 'stock.model_stock_move', move_rule_domain)

        inventory_rule_name = _("Rule: Inventories for %s") % self.name
        inventory_rule_domain = (
            "['|',"
            " ('location_ids.location_id','child_of', %d),"
            " ('location_ids.location_id.usage','in',['supplier','customer','production','inventory','transit','view'])"
            "]"
        ) % (self.lot_stock_id.id or 0)
        _create_or_update_rule(inventory_rule_name, 'stock.model_stock_inventory', inventory_rule_domain)

        scrap_rule_name = _("Rule: Scrap for %s") % self.name
        scrap_rule_domain = (
            "['|',"
            " ('location_id','child_of', %d),"
            " ('location_id.usage','in',['supplier','customer','production','inventory','transit','view'])"
            "]"
        ) % (self.lot_stock_id.id or 0)
        _create_or_update_rule(scrap_rule_name, 'stock.model_stock_scrap', scrap_rule_domain)

        return True


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def default_get(self, fields_list):
        """
        - Busca todos los almacenes a los que está asignado el usuario
        - Revisa el code (incoming/outgoing/internal) del contexto
        - Si encuentra exactamente 1 picking.type que coincide con ese code en esos almacenes, lo asigna
        """
        res = super(StockPicking, self).default_get(fields_list)

        user = self.env.user
        assigned_warehouses = self.env['stock.warehouse'].search([
            ('assigned_user_ids', 'in', user.id)
        ])
        picking_type_code = self.env.context.get('default_picking_type_code')
        if picking_type_code and assigned_warehouses:
            picking_types = self.env['stock.picking.type'].search([
                ('warehouse_id', 'in', assigned_warehouses.ids),
                ('code', '=', picking_type_code)
            ])
            if len(picking_types) == 1:
                res['picking_type_id'] = picking_types.id

        return res


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    @api.model
    def default_get(self, fields_list):
        """
        Asigna picking_type_id de la siguiente forma:
        - Si el usuario tiene varios almacenes asignados, se analizan sus manu_type_id (no nulos).
        - Si hay exactamente 1 manu_type_id, se asigna automáticamente.
        - Si hay más de uno, se asigna por un criterio (ej. ID menor).
        - Si no hay ninguno, no se asigna nada.
        """
        res = super(MrpProduction, self).default_get(fields_list)

        user = self.env.user
        assigned_warehouses = self.env['stock.warehouse'].search([
            ('assigned_user_ids', 'in', user.id)
        ])
        if assigned_warehouses:
            # Recogemos todos los manu_type_id de esos almacenes (eliminando duplicados y vacíos)
            manu_types = assigned_warehouses.mapped('manu_type_id').filtered(lambda pt: pt)
            manu_types = list(set(manu_types))  # quitar duplicados

            if len(manu_types) == 1:
                # Si solo hay uno, lo asignamos directamente
                res['picking_type_id'] = manu_types[0].id
            elif len(manu_types) > 1:
                # Si hay más de uno, escogemos el de ID más bajo (u otra lógica que desees)
                chosen_type = sorted(manu_types, key=lambda pt: pt.id)[0]
                res['picking_type_id'] = chosen_type.id

        return res
