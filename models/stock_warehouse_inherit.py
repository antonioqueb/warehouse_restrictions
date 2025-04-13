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
        y configura las reglas (ir.rule) para restringir datos a las ubicaciones
        e información relacionadas con este almacén, permitiendo al usuario
        ver también ubicaciones globales (supplier, customer, production...).
        """
        self.ensure_one()

        # 1) Grupo de seguridad para este almacén
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

        def _create_or_update_rule(rule_name, model_xmlid, domain_force):
            """Helper para crear/actualizar la regla con un dominio dado."""
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

        # ---------------------------------------------------------------------
        #  Reglas por modelo
        # ---------------------------------------------------------------------

        # 1) stock.picking
        picking_rule_name = _("Rule: Stock Pickings for %s") % self.name
        picking_rule_domain = "[('picking_type_id.warehouse_id','=', %d)]" % self.id
        _create_or_update_rule(picking_rule_name, 'stock.model_stock_picking', picking_rule_domain)

        # 2) mrp.production
        mrp_rule_name = _("Rule: MRP Productions for %s") % self.name
        mrp_rule_domain = "[('picking_type_id.warehouse_id','=', %d)]" % self.id
        _create_or_update_rule(mrp_rule_name, 'mrp.model_mrp_production', mrp_rule_domain)

        # 3) stock.picking.type (Kanban de Operaciones)
        picking_type_rule_name = _("Rule: Picking Types for %s") % self.name
        picking_type_rule_domain = "[('warehouse_id','=', %d)]" % self.id
        _create_or_update_rule(picking_type_rule_name, 'stock.model_stock_picking_type', picking_type_rule_domain)

        # 4) stock.location
        location_rule_name = _("Rule: Locations for %s") % self.name
        location_rule_domain = (
            "['|', "
            " ('id','child_of', %d), "
            " ('usage','in',['supplier','customer','production','inventory','view','transit'])]"
        ) % (self.lot_stock_id.id or 0)
        _create_or_update_rule(location_rule_name, 'stock.model_stock_location', location_rule_domain)

        # 5) stock.quant
        quant_rule_name = _("Rule: Quants for %s") % self.name
        quant_rule_domain = "[('location_id','child_of', %d)]" % (self.lot_stock_id.id or 0)
        _create_or_update_rule(quant_rule_name, 'stock.model_stock_quant', quant_rule_domain)

        # 6) stock.move
        # Aquí corregimos la cantidad de '|'
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

        # 7) stock.inventory
        inventory_rule_name = _("Rule: Inventories for %s") % self.name
        inventory_rule_domain = (
            "['|',"
            " ('location_ids.location_id','child_of', %d),"
            " ('location_ids.location_id.usage','in',['supplier','customer','production','inventory','transit','view'])"
            "]"
        ) % (self.lot_stock_id.id or 0)
        _create_or_update_rule(inventory_rule_name, 'stock.model_stock_inventory', inventory_rule_domain)

        # 8) stock.scrap
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
        """Forzamos que el picking_type_id sea del almacén asignado al usuario, si sólo tiene uno."""
        res = super(StockPicking, self).default_get(fields_list)
        user = self.env.user
        assigned_warehouses = self.env['stock.warehouse'].search([
            ('assigned_user_ids', 'in', user.id)
        ])
        if len(assigned_warehouses) == 1:
            wh = assigned_warehouses[0]
            # Ajusta según tu operación por defecto (in_type_id, out_type_id, etc.)
            if wh.in_type_id:
                res['picking_type_id'] = wh.in_type_id.id
        return res


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    @api.model
    def default_get(self, fields_list):
        """Forzamos que el picking_type_id sea del almacén asignado al usuario, si sólo tiene uno."""
        res = super(MrpProduction, self).default_get(fields_list)
        user = self.env.user
        assigned_warehouses = self.env['stock.warehouse'].search([
            ('assigned_user_ids', 'in', user.id)
        ])
        if len(assigned_warehouses) == 1:
            wh = assigned_warehouses[0]
            # Ajusta según tu lógica MRP. Si usas wh.int_type_id o un picking_type específico, etc.
            if wh.int_type_id:
                res['picking_type_id'] = wh.int_type_id.id
        return res
