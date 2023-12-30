# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.pool import PoolMeta
from trytond.model import fields
from trytond.i18n import gettext
from trytond.exceptions import UserError


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    aeat115_register = fields.Many2One('aeat.115.report.register',
        'AEAT 115 Register', readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_modify_exclude.add('aeat115_register')

    @classmethod
    def check_aeat115(cls, invoices):
        for invoice in invoices:
            if invoice.aeat115_register:
                raise UserError(
                    gettext('aeat_115.msg_draft_cancel_invoice_in_115report',
                        invoice=invoice.rec_name,
                        report=invoice.aeat115_register.report,
                    ))

    @classmethod
    def draft(cls, invoices):
        super().draft(invoices)
        cls.check_aeat115(invoices)

    @classmethod
    def cancel(cls, invoices):
        super().cancel(invoices)
        cls.check_aeat115(invoices)
