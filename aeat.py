# -*- coding: utf-8 -*-
from decimal import Decimal
import datetime
import calendar
import unicodedata
import sys

from retrofix import aeat115
from retrofix.record import Record, write as retrofix_write
from trytond.model import Workflow, ModelSQL, ModelView, fields, Unique
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool, If
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.transaction import Transaction


_DEPENDS = ['state']

_ZERO = Decimal("0.0")


def remove_accents(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text)
        if (unicodedata.category(c) != 'Mn'
                or c in ('\\u0327', '\\u0303'))  # Avoids normalize ç and ñ
        )
    # It converts nfd to nfc to allow unicode.decode()
    #return unicodedata.normalize('NFC', unicode_string_nfd)


class TemplateTaxCodeRelation(ModelSQL):
    '''
    AEAT 115 TaxCode Mapping Codes Relation
    '''
    __name__ = 'aeat.115.mapping-account.tax.code.template'

    mapping = fields.Many2One('aeat.115.template.mapping', 'Mapping',
        required=True)
    code = fields.Many2One('account.tax.code.template', 'Tax Code Template',
        required=True)


class TemplateTaxCodeMapping(ModelSQL):
    '''
    AEAT 115 TemplateTaxCode Mapping
    '''
    __name__ = 'aeat.115.template.mapping'

    aeat115_field = fields.Many2One('ir.model.field', 'Field',
        domain=[('module', '=', 'aeat_115')], required=True)
    code = fields.Many2Many('aeat.115.mapping-account.tax.code.template',
        'mapping', 'code', 'Tax Code Template')

    @classmethod
    def __setup__(cls):
        super(TemplateTaxCodeMapping, cls).__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('aeat115_field_uniq', Unique(t, t.aeat115_field),
                'Field must be unique.')
            ]

    def _get_mapping_value(self, mapping=None):
        pool = Pool()
        TaxCode = pool.get('account.tax.code')

        res = {}
        if not mapping or mapping.aeat115_field != self.aeat115_field:
            res['aeat115_field'] = self.aeat115_field.id
        res['code'] = []
        old_ids = set()
        new_ids = set()
        if mapping and len(mapping.code) > 0:
            old_ids = set([c.id for c in mapping.code])
        if len(self.code) > 0:
            new_ids = set([c.id for c in TaxCode.search([
                            ('template', 'in', [c.id for c in self.code])
                            ])])
        if not mapping or mapping.template != self:
            res['template'] = self.id
        if old_ids or new_ids:
            key = 'code'
            res[key] = []
            to_remove = old_ids - new_ids
            if to_remove:
                res[key].append(['remove', list(to_remove)])
            to_add = new_ids - old_ids
            if to_add:
                res[key].append(['add', list(to_add)])
            if not res[key]:
                del res[key]
        if not mapping and not res['code']:
            return  # There is nothing to create as there is no mapping
        return res


class UpdateChart(metaclass=PoolMeta):
    __name__ = 'account.update_chart'

    def transition_update(self):
        pool = Pool()
        MappingTemplate = pool.get('aeat.115.template.mapping')
        Mapping = pool.get('aeat.115.mapping')

        ret = super(UpdateChart, self).transition_update()

        # Update current values
        ids = []
        company = self.start.account.company.id
        for mapping in Mapping.search([
                    ('company', 'in', [company, None]),
                    ]):
            if not mapping.template:
                continue
            vals = mapping.template._get_mapping_value(mapping=mapping)
            if vals:
                Mapping.write([mapping], vals)
            ids.append(mapping.template.id)

        # Create new one's
        to_create = []
        for template in MappingTemplate.search([('id', 'not in', ids)]):
            vals = template._get_mapping_value()
            if vals:
                vals['company'] = company
                to_create.append(vals)
        if to_create:
            Mapping.create(to_create)

        return ret


class CreateChart(metaclass=PoolMeta):
    __name__ = 'account.create_chart'

    def transition_create_account(self):
        pool = Pool()
        MappingTemplate = pool.get('aeat.115.template.mapping')
        Mapping = pool.get('aeat.115.mapping')

        company = self.account.company.id

        ret = super(CreateChart, self).transition_create_account()
        to_create = []
        for template in MappingTemplate.search([]):
            vals = template._get_mapping_value()
            if vals:
                vals['company'] = company
                to_create.append(vals)

        Mapping.create(to_create)
        return ret


class TaxCodeRelation(ModelSQL):
    '''
    AEAT 115 TaxCode Mapping Codes Relation
    '''
    __name__ = 'aeat.115.mapping-account.tax.code'

    mapping = fields.Many2One('aeat.115.mapping', 'Mapping', required=True)
    code = fields.Many2One('account.tax.code', 'Tax Code', required=True)


class TaxCodeMapping(ModelSQL, ModelView):
    '''
    AEAT 115 TaxCode Mapping
    '''
    __name__ = 'aeat.115.mapping'

    company = fields.Many2One('company.company', 'Company',
        ondelete="RESTRICT")
    aeat115_field = fields.Many2One('ir.model.field', 'Field',
        domain=[('module', '=', 'aeat_115')], required=True)
    code = fields.Many2Many('aeat.115.mapping-account.tax.code', 'mapping',
        'code', 'Tax Code')
    code_by_companies = fields.Function(
        fields.Many2Many('aeat.115.mapping-account.tax.code', 'mapping',
        'code', 'Tax Code'), 'get_code_by_companies')
    template = fields.Many2One('aeat.115.template.mapping', 'Template')

    @classmethod
    def __setup__(cls):
        super(TaxCodeMapping, cls).__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('aeat115_field_uniq', Unique(t, t.company, t.aeat115_field),
                'Field must be unique.')
            ]

    @staticmethod
    def default_company():
        return Transaction().context.get('company') or None

    @classmethod
    def get_code_by_companies(cls, records, name):
        user_company = Transaction().context.get('company')
        res = dict((x.id, None) for x in records)
        for record in records:
            code_ids = []
            for code in record.code:
                if not code.company or code.company.id == user_company:
                    code_ids.append(code.id)
            res[record.id] = code_ids
        return res


class Report(Workflow, ModelSQL, ModelView):
    '''
    AEAT 115 Report
    '''
    __name__ = 'aeat.115.report'

    company = fields.Many2One('company.company', 'Company', required=True,
        states={
            'readonly': Eval('state').in_(['done', 'calculated']),
            }, depends=['state'])
    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'get_currency')

    # DR11501
    type = fields.Selection([
            ('I', 'Income'),
            ('U', 'Direct incomes in account'),
            ('G', 'Income on CCT'),
            ('N', 'Negative'),
            ], 'Declaration Type', required=True, sort=False, states={
                'readonly': Eval('state') == 'done',
            }, depends=_DEPENDS)
    company_vat = fields.Char('VAT')
    company_surname = fields.Char('Company Surname')
    company_name = fields.Char('Company Name')
    year = fields.Integer("Year", required=True,
        domain=[
            ('year', '>=', 1000),
            ('year', '<=', 9999)
            ],
        states={
            'readonly': Eval('state').in_(['done', 'calculated']),
            }, depends=_DEPENDS)
    period = fields.Selection([
            ('1T', 'First quarter'),
            ('2T', 'Second quarter'),
            ('3T', 'Third quarter'),
            ('4T', 'Fourth quarter'),
            ('01', 'January'),
            ('02', 'February'),
            ('03', 'March'),
            ('04', 'April'),
            ('05', 'May'),
            ('06', 'June'),
            ('07', 'July'),
            ('08', 'August'),
            ('09', 'September'),
            ('10', 'October'),
            ('11', 'November'),
            ('12', 'December'),
            ], 'Period', required=True, sort=False, states={
                'readonly': Eval('state').in_(['done', 'calculated']),
                }, depends=_DEPENDS)
    parties = fields.Integer("Parties",
        domain=[
            If(Eval('withholdings_payments_amount', 0) != 0,
                [
                    ('parties', '>', 0),
                    ('parties', '<=', 99999999),
                    ],
                ('parties', '=', 0)),
            ])
    withholdings_payments_base = fields.Numeric(
        'Withholding and Payments Base', digits=(15, 2))
    withholdings_payments_amount = fields.Numeric('Withholding and Payments',
        digits=(15, 2))
    to_deduce = fields.Numeric("To Deduce", digits=(15, 2),
        help="Exclusively in case of complementary self-assessment. "
        "Results to be entered from previous self-assessments for the same "
        "concept, year and period")
    result = fields.Function(fields.Numeric('Result', digits=(15, 2)),
        'get_result')
    complementary_declaration = fields.Boolean('Complementary Declaration')
    previous_declaration_receipt = fields.Char('Previous Declaration Receipt',
        size=13, states={
            'required': Bool(Eval('complementary_declaration')),
            }, depends=['complementary_declaration'])
    company_party = fields.Function(fields.Many2One('party.party',
            'Company Party', context={
                'company': Eval('company'),
            }, depends=['company']), 'on_change_with_company_party')
    bank_account = fields.Many2One('bank.account', 'Bank Account',
        domain=[
            ('owners', '=', Eval('company_party')),
            ], states={
            'required': Eval('type').in_(['U', 'D', 'X']),
            }, depends=['company_party', 'type'])

    # Footer
    state = fields.Selection([
            ('draft', 'Draft'),
            ('calculated', 'Calculated'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled')
            ], 'State', readonly=True)
    calculation_date = fields.DateTime('Calculation Date', readonly=True)
    file_ = fields.Binary('File', filename='filename', states={
            'invisible': Eval('state') != 'done',
            }, readonly=True)
    filename = fields.Function(fields.Char("File Name"), 'get_filename')

    @classmethod
    def __setup__(cls):
        super(Report, cls).__setup__()
        cls._order = [
            ('year', 'DESC'),
            ('period', 'DESC'),
            ('id', 'DESC'),
            ]
        cls._buttons.update({
                'draft': {
                    'invisible': ~Eval('state').in_(['calculated',
                            'cancelled']),
                    },
                'calculate': {
                    'invisible': ~Eval('state').in_(['draft']),
                    },
                'process': {
                    'invisible': ~Eval('state').in_(['calculated']),
                    },
                'cancel': {
                    'invisible': Eval('state').in_(['cancelled']),
                    },
                })
        cls._transitions |= set((
                ('draft', 'calculated'),
                ('draft', 'cancelled'),
                ('calculated', 'draft'),
                ('calculated', 'done'),
                ('calculated', 'cancelled'),
                ('done', 'cancelled'),
                ('cancelled', 'draft'),
                ))

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @classmethod
    def default_company_vat(cls):
        pool = Pool()
        Company = pool.get('company.company')
        company_id = cls.default_company()
        if company_id:
            company = Company(company_id)
            vat_code = company.party.tax_identifier and \
                company.party.tax_identifier.code or None
            if vat_code and vat_code.startswith('ES'):
                return vat_code[2:]
            return vat_code

    @staticmethod
    def default_parties():
        return 0

    @staticmethod
    def default_withholdings_payments_base():
        return _ZERO

    @staticmethod
    def default_withholdings_payments_amount():
        return _ZERO

    @staticmethod
    def default_to_deduce():
        return _ZERO

    @classmethod
    def default_company_party(cls):
        pool = Pool()
        Company = pool.get('company.company')
        company_id = cls.default_company()
        if company_id:
            return Company(company_id).party.id

    @fields.depends('company')
    def on_change_with_company_party(self, name=None):
        if self.company:
            return self.company.party.id

    @fields.depends('company')
    def on_change_with_company_surname(self, name=None):
        if self.company:
            return self.company.party.name.upper()

    @fields.depends('company')
    def on_change_with_company_vat(self, name=None):
        if self.company:
            tax_identifier = self.company.party.tax_identifier
            if tax_identifier and tax_identifier.code.startswith('ES'):
                return tax_identifier.code[2:]

    def get_currency(self, name):
        return self.company.currency.id

    def get_result(self, name):
        return (self.withholdings_payments_amount or _ZERO) - self.to_deduce

    def get_filename(self, name):
        return 'aeat115-%s-%s.txt' % (
            self.year, self.period)

    @classmethod
    @ModelView.button
    @Workflow.transition('calculated')
    def calculate(cls, reports):
        pool = Pool()
        Mapping = pool.get('aeat.115.mapping')
        Period = pool.get('account.period')
        TaxCode = pool.get('account.tax.code')
        Tax = pool.get('account.tax')
        TaxLine = pool.get('account.tax.line')
        Invoice = pool.get('account.invoice')

        for report in reports:
            mapping = {}
            for mapp in Mapping.search([
                    ('company', '=', report.company),
                    ]):
                for code in mapp.code_by_companies:
                    mapping[code.id] = mapp.aeat115_field.name

            period = report.period
            if 'T' in period:
                period = period[0]
                start_month = (int(period) - 1) * 3 + 1
                end_month = start_month + 2
            else:
                start_month = int(period)
                end_month = start_month

            year = report.year
            lday = calendar.monthrange(year, end_month)[1]
            periods = [p.id for p in Period.search([
                    ('start_date', '>=', datetime.date(year, start_month, 1)),
                    ('end_date', '<=', datetime.date(year, end_month, lday)),
                    ('company', '=', report.company),
                    ])]

            for field in mapping.values():
                setattr(report, field, _ZERO)

            parties = set()
            with Transaction().set_context(periods=periods):
                for code in TaxCode.browse(mapping.keys()):
                    value = getattr(report, mapping[code.id])
                    amount = value + code.amount
                    setattr(report, mapping[code.id], abs(amount))

                    # To count the numebr of parties we have to do it from the
                    # party in the realted moves of all codes used for the
                    # amount calculation
                    children = []
                    childs = TaxCode.search([
                            ('parent', 'child_of', [code]),
                            ])
                    if len(childs) == 1:
                        children = childs
                    else:
                        for child in childs:
                            if not child.childs and child.amount:
                                children.append(child)
                    for child in children:
                        if not child.lines:
                            continue
                        domain = [['OR'] + [x._line_domain for x in child.lines
                            if x.amount == 'tax']]
                        if domain == [['OR']]:
                            continue
                        domain.extend(Tax._amount_domain())
                        for tax_line in TaxLine.search(domain):
                            if (tax_line.move_line and tax_line.move_line.move
                                    and isinstance(tax_line.move_line.move.origin,
                                        Invoice)):
                                parties.add(tax_line.move_line.move.origin.party)
            report.parties = len(parties) if parties else 0
            report.save()

        cls.write(reports, {
                'calculation_date': datetime.datetime.now(),
                })

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def process(cls, reports):
        for report in reports:
            report.create_file()

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, reports):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, reports):
        pass

    def create_file(self):
        header = Record(aeat115.HEADER_RECORD)
        footer = Record(aeat115.FOOTER_RECORD)
        record = Record(aeat115.RECORD)
        columns = [x for x in self.__class__._fields if x != 'report']
        for column in columns:
            value = getattr(self, column, None)
            if not value:
                continue
            if column == 'year' or column == 'parties':
                value = str(getattr(self, column, 0))
            elif column == 'bank_account':
                value = next((n.number_compact for n in value.numbers
                        if n.type == 'iban'), '')
            if column in header._fields:
                setattr(header, column, value)
            if column in record._fields:
                setattr(record, column, value)
            if column in footer._fields:
                setattr(footer, column, value)
        records = [header, record, footer]
        try:
            data = retrofix_write(records, separator='')
        except AssertionError as e:
            raise UserError(str(e))
        data = remove_accents(data).upper()
        if isinstance(data, str):
            data = data.encode('iso-8859-1')
        self.file_ = self.__class__.file_.cast(data)
        self.save()
