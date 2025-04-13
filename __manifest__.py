# -*- coding: utf-8 -*-
{
    'name': 'Warehouse Restrictions',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Stock',
    'summary': 'Asigna usuarios a almacenes y crea restricciones automáticas de visibilidad.',
    'author': 'Alphaqueb Consulting SAS',
    'website': 'https://www.alphaqueb.com/',
    'license': 'LGPL-3',
    'depends': [
        'stock',
        'mrp',  # Necesario para restringir órdenes de producción
    ],
    'data': [
        'security/security.xml',           # Primero cargas el archivo de seguridad
        'security/ir.model.access.csv',    # Después los accesos por CSV
        'views/stock_warehouse_view_inherit.xml',
    ],
    'installable': True,
    'application': False,
}
