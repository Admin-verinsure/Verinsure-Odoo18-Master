# Create new file: models/form_analytics.py
from odoo import models, fields, api, tools
from datetime import datetime, timedelta

class FormAnalytics(models.Model):
    _name = 'form.analytics'
    _description = 'Form Analytics'
    _auto = False  # This is a view model
    _order = 'date desc'

    form_id = fields.Many2one('form.builder', string='Form', readonly=True)
    form_name = fields.Char(string='Form Name', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    submissions = fields.Integer(string='Submissions', readonly=True)
    views = fields.Integer(string='Views', readonly=True)
    conversion_rate = fields.Float(string='Conversion Rate (%)', readonly=True)
    country = fields.Char(string='Country', readonly=True)

# Replace the existing init() method in FormAnalytics class
    def init(self):
        cr = self.env.cr
        # ensure dependent tables exist
        cr.execute("""
            SELECT tablename FROM pg_catalog.pg_tables 
            WHERE tablename IN ('form_view_tracker', 'form_submission', 'form_builder')
        """)
        existing_tables = {row[0] for row in cr.fetchall()}
        if not {'form_view_tracker', 'form_submission', 'form_builder'}.issubset(existing_tables):
            return  # ✅ skip if base tables are not ready

        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH daily_submissions AS (
                    SELECT 
                        fs.form_id,
                        fs.submitted_on::date as submission_date,
                        COUNT(*) as daily_submissions
                    FROM form_submission fs
                    GROUP BY fs.form_id, fs.submitted_on::date
                ),
                daily_views AS (
                    SELECT 
                        fvt.form_id,
                        fvt.view_date::date as view_date,
                        COUNT(*) as daily_views,
                        fvt.country
                    FROM form_view_tracker fvt
                    GROUP BY fvt.form_id, fvt.view_date::date, fvt.country
                )
                SELECT 
                    row_number() OVER () AS id,
                    fb.id as form_id,
                    fb.name as form_name,
                    COALESCE(ds.submission_date, dv.view_date, fb.created_date::date) as date,
                    COALESCE(ds.daily_submissions, 0) as submissions,
                    COALESCE(dv.daily_views, 0) as views,
                    CASE 
                        WHEN COALESCE(dv.daily_views, 0) > 0 
                        THEN (COALESCE(ds.daily_submissions, 0)::float / dv.daily_views * 100)
                        ELSE 0 
                    END as conversion_rate,
                    COALESCE(dv.country, 'Unknown') as country
                FROM form_builder fb
                FULL OUTER JOIN daily_submissions ds ON ds.form_id = fb.id
                FULL OUTER JOIN daily_views dv ON dv.form_id = fb.id AND dv.view_date = ds.submission_date
                WHERE fb.id IS NOT NULL
            )
        """ % self._table)


class FormViewTracker(models.Model):
    _name = 'form.view.tracker'
    _description = 'Form View Tracker'
    _table = 'form_view_tracker'
    
    form_id = fields.Many2one('form.builder', string='Form', required=True, ondelete='cascade')
    view_date = fields.Datetime(string='View Date', default=fields.Datetime.now)
    ip_address = fields.Char(string='IP Address')
    country = fields.Char(string='Country', default='Unknown')
    user_agent = fields.Text(string='User Agent')


class FormRegionalAnalytics(models.Model):
    _name = 'form.regional.analytics'
    _description = 'Form Regional Analytics'
    _auto = False
    _table = 'form_regional_analytics_view'
    
    form_id = fields.Many2one('form.builder', string='Form', readonly=True)
    country = fields.Char(string='Country', readonly=True)
    total_views = fields.Integer(string='Total Views', readonly=True)
    total_submissions = fields.Integer(string='Total Submissions', readonly=True)
    conversion_rate = fields.Float(string='Conversion Rate (%)', readonly=True)
    
    def init(self):
        cr = self.env.cr
        cr.execute("""
            SELECT tablename FROM pg_catalog.pg_tables 
            WHERE tablename IN ('form_view_tracker', 'form_submission', 'form_builder')
        """)
        existing_tables = {row[0] for row in cr.fetchall()}
        if not {'form_view_tracker', 'form_submission', 'form_builder'}.issubset(existing_tables):
            return

            
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT 
                    row_number() OVER () AS id,
                    fb.id as form_id,
                    COALESCE(fvt.country, 'Unknown') as country,
                    COUNT(DISTINCT fvt.id) as total_views,
                    COUNT(DISTINCT fs.id) as total_submissions,
                    CASE 
                        WHEN COUNT(DISTINCT fvt.id) > 0 
                        THEN (COUNT(DISTINCT fs.id)::float / COUNT(DISTINCT fvt.id) * 100)
                        ELSE 0 
                    END as conversion_rate
                FROM form_builder fb
                LEFT JOIN form_view_tracker fvt ON fvt.form_id = fb.id
                LEFT JOIN form_submission fs ON fs.form_id = fb.id
                GROUP BY fb.id, COALESCE(fvt.country, 'Unknown')
                HAVING COUNT(DISTINCT fvt.id) > 0 OR COUNT(DISTINCT fs.id) > 0
            )
        """ % self._table)