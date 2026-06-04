# -*- coding: utf-8 -*-
"""
auth.otp.challenge model
========================
Stores hashed OTP challenges with full security controls:
- SHA-256 hashed OTP (never plain-text)
- 5-minute expiry
- 5-attempt brute-force lockout
- State machine: pending → verified / expired / cancelled
- Replay-attack prevention via state check
- Indexed fields for performance
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Security constants
OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 5
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
OTP_CLEANUP_DAYS = 30


def _generate_otp() -> str:
    """
    Generate a cryptographically secure numeric OTP.
    Uses secrets.choice() — never random.randint() or random.choices().
    """
    digits = '0123456789'
    return ''.join(secrets.choice(digits) for _ in range(OTP_LENGTH))


def _hash_otp(otp: str, salt: str) -> str:
    """
    Hash OTP with a per-record salt using SHA-256.
    Salting prevents rainbow-table attacks against the hashed column.
    """
    value = f"{salt}:{otp}"
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class AuthOtpChallenge(models.Model):
    _name = 'auth.otp.challenge'
    _description = 'Email OTP Authentication Challenge'
    _order = 'create_date desc'
    _rec_name = 'user_id'

    # ── Fields ────────────────────────────────────────────────────────────────

    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        ondelete='cascade',
        index=True,
    )
    otp_hash = fields.Char(
        string='OTP Hash',
        required=True,
        copy=False,
        help='SHA-256 hash of salt:otp — never store plain OTP.',
    )
    otp_salt = fields.Char(
        string='OTP Salt',
        required=True,
        copy=False,
        help='Per-record random salt for hash uniqueness.',
    )
    expiry_time = fields.Datetime(
        string='Expiry Time',
        required=True,
        index=True,
    )
    attempt_count = fields.Integer(
        string='Failed Attempts',
        default=0,
        help='Number of incorrect OTP submissions.',
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('verified', 'Verified'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        string='State',
        default='pending',
        required=True,
        index=True,
    )
    ip_address = fields.Char(
        string='IP Address',
        help='Client IP at time of OTP generation.',
    )
    user_agent = fields.Char(
        string='User Agent',
        help='Browser user-agent at time of OTP generation.',
    )
    last_resend = fields.Datetime(
        string='Last Resend At',
        help='Timestamp of last OTP resend to enforce cooldown.',
    )

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('attempt_count')
    def _check_attempt_count(self):
        for rec in self:
            if rec.attempt_count < 0:
                raise ValidationError(_('Attempt count cannot be negative.'))

    # ── Business Logic ────────────────────────────────────────────────────────

    @api.model
    def create_challenge(self, user, ip_address=None, user_agent=None):
        """
        Create a new OTP challenge for a user.

        Cancels any existing pending challenge to prevent OTP accumulation.
        Generates a fresh OTP, hashes it, and sends the email.

        Returns:
            tuple(auth.otp.challenge, str): record and plain OTP (for email only)
        """
        # Cancel existing pending challenges for this user
        existing = self.search([
            ('user_id', '=', user.id),
            ('state', '=', 'pending'),
        ])
        if existing:
            existing.sudo().write({'state': 'cancelled'})
            _logger.info(
                'auth.otp: Cancelled %d existing pending challenge(s) for user %s (id=%d)',
                len(existing), user.login, user.id,
            )

        plain_otp = _generate_otp()
        salt = secrets.token_hex(16)
        otp_hash = _hash_otp(plain_otp, salt)
        expiry = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)

        challenge = self.sudo().create({
            'user_id': user.id,
            'otp_hash': otp_hash,
            'otp_salt': salt,
            'expiry_time': expiry,
            'state': 'pending',
            'ip_address': ip_address,
            'user_agent': (user_agent or '')[:512],
        })

        _logger.info(
            'auth.otp: OTP challenge created for user %s (id=%d) from IP %s | challenge_id=%d',
            user.login, user.id, ip_address, challenge.id,
        )
        return challenge, plain_otp

    def verify_otp(self, submitted_otp: str) -> bool:
        """
        Verify a submitted OTP against this challenge.

        Security controls:
        - Rejects non-pending state (prevents replay)
        - Checks expiry before hash comparison
        - Increments attempt counter
        - Locks out after MAX_ATTEMPTS
        - Clears sensitive data on success

        Returns:
            bool: True if OTP is correct and challenge is valid.
        """
        self.ensure_one()

        if self.state != 'pending':
            _logger.warning(
                'auth.otp: Verification attempted on non-pending challenge %d (state=%s) for user %s',
                self.id, self.state, self.user_id.login,
            )
            return False

        # Expiry check
        if datetime.utcnow() > fields.Datetime.from_string(self.expiry_time):
            self.sudo().write({'state': 'expired'})
            _logger.info(
                'auth.otp: Challenge %d expired for user %s',
                self.id, self.user_id.login,
            )
            return False

        # Compute hash of submitted OTP using this record's salt
        submitted_hash = _hash_otp(submitted_otp.strip(), self.otp_salt)

        # Constant-time comparison to prevent timing attacks
        if secrets.compare_digest(submitted_hash, self.otp_hash):
            self.sudo().write({
                'state': 'verified',
                'otp_hash': '',   # Scrub hash after success
                'otp_salt': '',   # Scrub salt after success
            })
            _logger.info(
                'auth.otp: OTP verified successfully for user %s (id=%d) | challenge_id=%d',
                self.user_id.login, self.user_id.id, self.id,
            )
            return True

        # Wrong OTP: increment attempt counter
        new_count = self.attempt_count + 1
        vals = {'attempt_count': new_count}

        if new_count >= MAX_ATTEMPTS:
            vals['state'] = 'cancelled'
            _logger.warning(
                'auth.otp: Max OTP attempts (%d) reached for user %s (id=%d) | challenge_id=%d — challenge cancelled',
                MAX_ATTEMPTS, self.user_id.login, self.user_id.id, self.id,
            )
        else:
            _logger.warning(
                'auth.otp: Failed OTP attempt %d/%d for user %s (id=%d) | challenge_id=%d',
                new_count, MAX_ATTEMPTS, self.user_id.login, self.user_id.id, self.id,
            )

        self.sudo().write(vals)
        return False

    def can_resend(self) -> bool:
        """
        Check if enough time has passed since last resend.
        Prevents mail flooding (60-second cooldown).
        """
        self.ensure_one()
        if not self.last_resend:
            return True
        elapsed = (datetime.utcnow() - fields.Datetime.from_string(self.last_resend)).total_seconds()
        return elapsed >= RESEND_COOLDOWN_SECONDS

    def resend_seconds_remaining(self) -> int:
        """Return seconds until resend is allowed again (0 if allowed)."""
        self.ensure_one()
        if not self.last_resend:
            return 0
        elapsed = (datetime.utcnow() - fields.Datetime.from_string(self.last_resend)).total_seconds()
        remaining = RESEND_COOLDOWN_SECONDS - elapsed
        return max(0, int(remaining))

    @api.model
    def cleanup_expired_records(self):
        """
        Scheduled action: remove OTP records older than OTP_CLEANUP_DAYS.
        Called by ir.cron. Uses sudo to bypass record rules.
        """
        cutoff = datetime.utcnow() - timedelta(days=OTP_CLEANUP_DAYS)
        old_records = self.sudo().search([('create_date', '<', fields.Datetime.to_string(cutoff))])
        count = len(old_records)
        old_records.unlink()
        _logger.info('auth.otp: Cleanup removed %d OTP records older than %d days.', count, OTP_CLEANUP_DAYS)
