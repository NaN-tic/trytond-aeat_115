# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from . import aeat
from . import invoice


def register():
    Pool.register(
        aeat.TemplateTaxCodeMapping,
        aeat.TemplateTaxCodeRelation,
        aeat.TaxCodeMapping,
        aeat.TaxCodeRelation,
        aeat.Report,
        aeat.Register,
        invoice.Invoice,
        module='aeat_115', type_='model')
    Pool.register(
        aeat.CreateChart,
        aeat.UpdateChart,
        module='aeat_115', type_='wizard')
