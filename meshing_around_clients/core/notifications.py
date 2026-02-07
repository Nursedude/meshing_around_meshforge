"""
Notification system for Meshing-Around Clients.
Provides email and SMS notification capabilities for alerts.

This module implements the notification framework - actual sending
requires valid credentials to be configured in the config file.
"""

import logging
import smtplib
import threading
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

from .models import Alert
from .config import Config


logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Types of notifications."""
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
    SOUND = "sound"


@dataclass
class EmailConfig:
    """Email notification configuration."""
    enabled: bool = False
    smtp_server: str = ""
    smtp_port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    to_addresses: List[str] = field(default_factory=list)
    subject_prefix: str = "[MeshForge Alert]"


@dataclass
class SMSConfig:
    """SMS notification configuration via gateway."""
    enabled: bool = False
    gateway_type: str = "email"  # email, twilio, http
    # Email-to-SMS gateway settings
    carrier_gateway: str = ""  # e.g., "txt.att.net", "vtext.com"
    phone_numbers: List[str] = field(default_factory=list)
    # HTTP gateway settings
    api_url: str = ""
    api_key: str = ""
    # Twilio settings
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""


@dataclass
class NotificationConfig:
    """Overall notification configuration."""
    email: EmailConfig = field(default_factory=EmailConfig)
    sms: SMSConfig = field(default_factory=SMSConfig)
    # Rate limiting
    min_alert_interval_seconds: int = 60  # Minimum time between same alert type
    quiet_hours_start: Optional[str] = None  # e.g., "22:00"
    quiet_hours_end: Optional[str] = None  # e.g., "07:00"
    # Filtering
    min_severity: int = 2  # Only notify for severity >= this


class NotificationManager:
    """
    Manages sending notifications for alerts.

    Supports email and SMS notifications with rate limiting and quiet hours.
    Thread-safe implementation.
    """

    # Common US carrier email-to-SMS gateways
    CARRIER_GATEWAYS = {
        "att": "txt.att.net",
        "tmobile": "tmomail.net",
        "verizon": "vtext.com",
        "sprint": "messaging.sprintpcs.com",
        "uscellular": "email.uscc.net",
        "virgin": "vmobl.com",
        "boost": "sms.myboostmobile.com",
        "cricket": "sms.cricketwireless.net",
        "metropcs": "mymetropcs.com",
        "googlefi": "msg.fi.google.com",
    }

    def __init__(self, config: Config, notification_config: Optional[NotificationConfig] = None):
        self.config = config
        self.notification_config = notification_config or NotificationConfig()
        self._lock = threading.Lock()
        self._last_alerts: Dict[str, datetime] = {}  # alert_type -> last_sent
        self._send_queue: List[tuple] = []

    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        start = self.notification_config.quiet_hours_start
        end = self.notification_config.quiet_hours_end

        if not start or not end:
            return False

        try:
            now = datetime.now().time()
            start_time = datetime.strptime(start, "%H:%M").time()
            end_time = datetime.strptime(end, "%H:%M").time()

            # Handle overnight quiet hours (e.g., 22:00 to 07:00)
            if start_time > end_time:
                return now >= start_time or now <= end_time
            else:
                return start_time <= now <= end_time
        except ValueError:
            return False

    def _should_notify(self, alert: Alert) -> bool:
        """Check if notification should be sent for this alert."""
        # Check severity
        if alert.severity < self.notification_config.min_severity:
            return False

        # Check quiet hours
        if self._is_quiet_hours():
            logger.debug("Notification suppressed: quiet hours")
            return False

        # Check rate limiting
        with self._lock:
            last_sent = self._last_alerts.get(alert.alert_type.value)
            if last_sent:
                elapsed = (datetime.now(timezone.utc) - last_sent).total_seconds()
                if elapsed < self.notification_config.min_alert_interval_seconds:
                    logger.debug("Notification suppressed: rate limit")
                    return False

        return True

    def _record_notification(self, alert: Alert) -> None:
        """Record that a notification was sent for rate limiting."""
        with self._lock:
            self._last_alerts[alert.alert_type.value] = datetime.now(timezone.utc)

    # ==================== Email Notifications ====================

    def send_email(self, alert: Alert) -> bool:
        """
        Send email notification for an alert.

        Returns True if sent successfully, False otherwise.
        """
        email_config = self.notification_config.email

        if not email_config.enabled:
            return False

        if not all([email_config.smtp_server, email_config.username,
                    email_config.from_address, email_config.to_addresses]):
            logger.warning("Email notification not configured properly")
            return False

        if not self._should_notify(alert):
            return False

        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = email_config.from_address
            msg['To'] = ", ".join(email_config.to_addresses)
            msg['Subject'] = f"{email_config.subject_prefix} {alert.title}"

            body = self._format_email_body(alert)
            msg.attach(MIMEText(body, 'plain'))

            # Send email
            with smtplib.SMTP(email_config.smtp_server, email_config.smtp_port) as server:
                if email_config.use_tls:
                    server.starttls()
                if email_config.password:
                    server.login(email_config.username, email_config.password)
                server.sendmail(
                    email_config.from_address,
                    email_config.to_addresses,
                    msg.as_string()
                )

            self._record_notification(alert)
            logger.info("Email notification sent for alert: %s", alert.title)
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("Email authentication failed - check credentials")
            return False
        except smtplib.SMTPException as e:
            logger.error("Email notification failed: %s", e)
            return False
        except OSError as e:
            logger.error("Email connection failed: %s", e)
            return False

    def _format_email_body(self, alert: Alert) -> str:
        """Format alert as email body."""
        return f"""MeshForge Alert Notification

Alert Type: {alert.alert_type.value.upper()}
Severity: {alert.severity_label}
Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S') if alert.timestamp else 'N/A'}

Title: {alert.title}

Message:
{alert.message}

Source Node: {alert.source_node or 'N/A'}

---
This is an automated notification from MeshForge.
Configure notifications in mesh_client.ini to change these settings.
"""

    # ==================== SMS Notifications ====================

    def send_sms(self, alert: Alert) -> bool:
        """
        Send SMS notification for an alert.

        Supports multiple gateway types:
        - email: Email-to-SMS gateway (most carriers)
        - http: Generic HTTP API gateway
        - twilio: Twilio API

        Returns True if sent successfully, False otherwise.
        """
        sms_config = self.notification_config.sms

        if not sms_config.enabled:
            return False

        if not self._should_notify(alert):
            return False

        gateway_type = sms_config.gateway_type.lower()

        if gateway_type == "email":
            return self._send_sms_via_email(alert)
        elif gateway_type == "http":
            return self._send_sms_via_http(alert)
        elif gateway_type == "twilio":
            return self._send_sms_via_twilio(alert)
        else:
            logger.warning("Unknown SMS gateway type: %s", gateway_type)
            return False

    def _send_sms_via_email(self, alert: Alert) -> bool:
        """Send SMS via email-to-SMS gateway."""
        sms_config = self.notification_config.sms
        email_config = self.notification_config.email

        if not email_config.smtp_server:
            logger.warning("SMS via email requires email to be configured")
            return False

        if not sms_config.carrier_gateway or not sms_config.phone_numbers:
            logger.warning("SMS carrier gateway or phone numbers not configured")
            return False

        # Format short message for SMS
        sms_text = self._format_sms_body(alert)

        success = False
        for phone in sms_config.phone_numbers:
            # Clean phone number (remove non-digits)
            clean_phone = ''.join(c for c in phone if c.isdigit())
            sms_address = f"{clean_phone}@{sms_config.carrier_gateway}"

            try:
                msg = MIMEText(sms_text)
                msg['From'] = email_config.from_address
                msg['To'] = sms_address
                msg['Subject'] = ""  # SMS gateways often ignore subject

                with smtplib.SMTP(email_config.smtp_server, email_config.smtp_port) as server:
                    if email_config.use_tls:
                        server.starttls()
                    if email_config.password:
                        server.login(email_config.username, email_config.password)
                    server.sendmail(email_config.from_address, [sms_address], msg.as_string())

                success = True
                logger.info("SMS sent via email gateway to %s", clean_phone[-4:])

            except (smtplib.SMTPException, OSError) as e:
                logger.error("SMS via email failed for %s: %s", clean_phone[-4:], e)

        if success:
            self._record_notification(alert)
        return success

    def _send_sms_via_http(self, alert: Alert) -> bool:
        """Send SMS via HTTP API gateway."""
        sms_config = self.notification_config.sms

        if not sms_config.api_url or not sms_config.api_key:
            logger.warning("SMS HTTP gateway not configured")
            return False

        sms_text = self._format_sms_body(alert)

        success = False
        for phone in sms_config.phone_numbers:
            clean_phone = ''.join(c for c in phone if c.isdigit())

            try:
                # Generic HTTP POST - adapt parameters to your gateway
                data = urllib.parse.urlencode({
                    'api_key': sms_config.api_key,
                    'to': clean_phone,
                    'message': sms_text
                }).encode('utf-8')

                req = urllib.request.Request(sms_config.api_url, data=data)
                req.add_header('Content-Type', 'application/x-www-form-urlencoded')

                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.status == 200:
                        success = True
                        logger.info("SMS sent via HTTP gateway to %s", clean_phone[-4:])
                    else:
                        logger.warning("SMS HTTP gateway returned status %d", response.status)

            except urllib.error.URLError as e:
                logger.error("SMS HTTP gateway failed: %s", e)

        if success:
            self._record_notification(alert)
        return success

    def _send_sms_via_twilio(self, alert: Alert) -> bool:
        """Send SMS via Twilio API."""
        sms_config = self.notification_config.sms

        if not all([sms_config.twilio_account_sid, sms_config.twilio_auth_token,
                    sms_config.twilio_from_number]):
            logger.warning("Twilio SMS not configured")
            return False

        sms_text = self._format_sms_body(alert)

        success = False
        for phone in sms_config.phone_numbers:
            clean_phone = ''.join(c for c in phone if c.isdigit())
            if not clean_phone.startswith('+'):
                clean_phone = '+1' + clean_phone  # Default to US

            try:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{sms_config.twilio_account_sid}/Messages.json"
                data = urllib.parse.urlencode({
                    'From': sms_config.twilio_from_number,
                    'To': clean_phone,
                    'Body': sms_text
                }).encode('utf-8')

                # Create request with basic auth
                req = urllib.request.Request(url, data=data)
                credentials = f"{sms_config.twilio_account_sid}:{sms_config.twilio_auth_token}"
                import base64
                auth_header = base64.b64encode(credentials.encode()).decode()
                req.add_header('Authorization', f'Basic {auth_header}')

                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.status in (200, 201):
                        success = True
                        logger.info("SMS sent via Twilio to %s", clean_phone[-4:])
                    else:
                        logger.warning("Twilio returned status %d", response.status)

            except urllib.error.URLError as e:
                logger.error("Twilio SMS failed: %s", e)

        if success:
            self._record_notification(alert)
        return success

    def _format_sms_body(self, alert: Alert) -> str:
        """Format alert as SMS body (160 char limit)."""
        # Keep it short for SMS
        severity_icon = {1: "i", 2: "!", 3: "!!", 4: "!!!"}
        icon = severity_icon.get(alert.severity, "*")

        text = f"[{icon}] {alert.title}: {alert.message}"

        # Truncate to SMS length
        if len(text) > 155:
            text = text[:152] + "..."

        return text

    # ==================== Unified Interface ====================

    def notify(self, alert: Alert, channels: Optional[List[NotificationType]] = None) -> Dict[str, bool]:
        """
        Send notification through specified channels.

        Args:
            alert: The alert to send
            channels: List of notification types, or None for all enabled

        Returns:
            Dict mapping channel name to success status
        """
        results = {}

        if channels is None:
            channels = []
            if self.notification_config.email.enabled:
                channels.append(NotificationType.EMAIL)
            if self.notification_config.sms.enabled:
                channels.append(NotificationType.SMS)

        for channel in channels:
            if channel == NotificationType.EMAIL:
                results['email'] = self.send_email(alert)
            elif channel == NotificationType.SMS:
                results['sms'] = self.send_sms(alert)

        return results

    def notify_async(self, alert: Alert, channels: Optional[List[NotificationType]] = None) -> None:
        """
        Send notification asynchronously (non-blocking).

        Args:
            alert: The alert to send
            channels: List of notification types, or None for all enabled
        """
        thread = threading.Thread(
            target=self.notify,
            args=(alert, channels),
            daemon=True
        )
        thread.start()

    # ==================== Configuration Loading ====================

    @classmethod
    def from_config_parser(cls, config: Config, parser) -> 'NotificationManager':
        """
        Create NotificationManager from ConfigParser sections.

        Expected sections in INI file:
        [email_notifications]
        [sms_notifications]
        """
        notification_config = NotificationConfig()

        # Email configuration
        if parser.has_section('email_notifications'):
            notification_config.email = EmailConfig(
                enabled=parser.getboolean('email_notifications', 'enabled', fallback=False),
                smtp_server=parser.get('email_notifications', 'smtp_server', fallback=''),
                smtp_port=parser.getint('email_notifications', 'smtp_port', fallback=587),
                use_tls=parser.getboolean('email_notifications', 'use_tls', fallback=True),
                username=parser.get('email_notifications', 'username', fallback=''),
                password=parser.get('email_notifications', 'password', fallback=''),
                from_address=parser.get('email_notifications', 'from_address', fallback=''),
                to_addresses=[
                    addr.strip()
                    for addr in parser.get('email_notifications', 'to_addresses', fallback='').split(',')
                    if addr.strip()
                ],
                subject_prefix=parser.get('email_notifications', 'subject_prefix', fallback='[MeshForge Alert]')
            )

        # SMS configuration
        if parser.has_section('sms_notifications'):
            notification_config.sms = SMSConfig(
                enabled=parser.getboolean('sms_notifications', 'enabled', fallback=False),
                gateway_type=parser.get('sms_notifications', 'gateway_type', fallback='email'),
                carrier_gateway=parser.get('sms_notifications', 'carrier_gateway', fallback=''),
                phone_numbers=[
                    num.strip()
                    for num in parser.get('sms_notifications', 'phone_numbers', fallback='').split(',')
                    if num.strip()
                ],
                api_url=parser.get('sms_notifications', 'api_url', fallback=''),
                api_key=parser.get('sms_notifications', 'api_key', fallback=''),
                twilio_account_sid=parser.get('sms_notifications', 'twilio_account_sid', fallback=''),
                twilio_auth_token=parser.get('sms_notifications', 'twilio_auth_token', fallback=''),
                twilio_from_number=parser.get('sms_notifications', 'twilio_from_number', fallback='')
            )

        # Global notification settings
        if parser.has_section('notifications'):
            notification_config.min_alert_interval_seconds = parser.getint(
                'notifications', 'min_interval_seconds', fallback=60
            )
            notification_config.quiet_hours_start = parser.get(
                'notifications', 'quiet_hours_start', fallback=None
            )
            notification_config.quiet_hours_end = parser.get(
                'notifications', 'quiet_hours_end', fallback=None
            )
            notification_config.min_severity = parser.getint(
                'notifications', 'min_severity', fallback=2
            )

        return cls(config, notification_config)

    def get_status(self) -> Dict[str, Any]:
        """Get current notification system status."""
        return {
            "email": {
                "enabled": self.notification_config.email.enabled,
                "configured": bool(self.notification_config.email.smtp_server),
                "recipients": len(self.notification_config.email.to_addresses)
            },
            "sms": {
                "enabled": self.notification_config.sms.enabled,
                "gateway_type": self.notification_config.sms.gateway_type,
                "recipients": len(self.notification_config.sms.phone_numbers)
            },
            "quiet_hours": {
                "active": self._is_quiet_hours(),
                "start": self.notification_config.quiet_hours_start,
                "end": self.notification_config.quiet_hours_end
            },
            "min_severity": self.notification_config.min_severity
        }
