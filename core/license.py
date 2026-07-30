import hashlib
import time
import uuid
from typing import Dict, Any, Optional

class LicenseTier:
    FREE = "FREE"
    PRO = "PRO"
    PROP_FIRM = "PROP_FIRM"

class LicenseManager:
    """
    Handles commercial licensing, machine binding, tier validation,
    and anti-piracy checks for Maty Grid Bot.
    """
    SECRET_SALT = "MatyGridBot_SaaS_2026_SecureKey"

    def __init__(self, license_key: Optional[str] = None, account_id: Optional[str] = None):
        self.license_key = license_key.strip() if license_key else ""
        self.account_id = str(account_id).strip() if account_id else ""
        self.machine_id = self._get_machine_id()
        self.cached_info: Optional[Dict[str, Any]] = None
        self.validate()

    def _get_machine_id(self) -> str:
        """Generates a stable machine fingerprint for hardware binding."""
        try:
            mac_num = uuid.getnode()
            return hashlib.sha256(f"{mac_num}-{self.SECRET_SALT}".encode()).hexdigest()[:16]
        except Exception:
            return "DEFAULT_HW_ID"

    def generate_key(self, tier: str, account_id: str = "", days_valid: int = 30) -> str:
        """
        Helper method for SaaS admin to generate signed license keys.
        Format: MATY-[TIER]-[EXPIRE_TIMESTAMP_HEX]-[SIGNATURE_HASH]
        """
        expire_ts = int(time.time()) + (days_valid * 86400)
        expire_hex = hex(expire_ts)[2:].upper()
        raw_payload = f"{tier.upper()}:{account_id.strip()}:{expire_hex}:{self.SECRET_SALT}"
        sig = hashlib.sha256(raw_payload.encode()).hexdigest()[:8].upper()
        return f"MATY-{tier.upper()}-{expire_hex}-{sig}"

    def validate(self) -> Dict[str, Any]:
        """
        Validates the current license key. Returns license metadata dictionary.
        """
        if not self.license_key:
            info = {
                "valid": True,
                "tier": LicenseTier.FREE,
                "max_pairs": 1,
                "prop_guard": False,
                "telegram_alerts": False,
                "message": "Free Demo Sandbox Mode"
            }
            self.cached_info = info
            return info

        parts = self.license_key.upper().split("-")
        if len(parts) != 4 or parts[0] != "MATY":
            info = {
                "valid": False,
                "tier": LicenseTier.FREE,
                "max_pairs": 1,
                "prop_guard": False,
                "telegram_alerts": False,
                "message": "Invalid License Key Format"
            }
            self.cached_info = info
            return info

        tier_code, expire_hex, signature = parts[1], parts[2], parts[3]

        # Verify Signature
        raw_payload = f"{tier_code}:{self.account_id}:{expire_hex}:{self.SECRET_SALT}"
        expected_sig_with_acc = hashlib.sha256(raw_payload.encode()).hexdigest()[:8].upper()
        raw_payload_any = f"{tier_code}::{expire_hex}:{self.SECRET_SALT}"
        expected_sig_any = hashlib.sha256(raw_payload_any.encode()).hexdigest()[:8].upper()

        if signature not in (expected_sig_with_acc, expected_sig_any):
            info = {
                "valid": False,
                "tier": LicenseTier.FREE,
                "max_pairs": 1,
                "prop_guard": False,
                "telegram_alerts": False,
                "message": "Invalid License Signature"
            }
            self.cached_info = info
            return info

        # Verify Expiration
        try:
            expire_ts = int(expire_hex, 16)
        except ValueError:
            expire_ts = 0

        if time.time() > expire_ts:
            info = {
                "valid": False,
                "tier": LicenseTier.FREE,
                "max_pairs": 1,
                "prop_guard": False,
                "telegram_alerts": False,
                "message": "License Key Expired"
            }
            self.cached_info = info
            return info

        # Derive Tier Capabilities
        tier = LicenseTier.PROP_FIRM if tier_code == "PROP" else (LicenseTier.PRO if tier_code == "PRO" else LicenseTier.FREE)
        max_pairs = 99 if tier == LicenseTier.PROP_FIRM else (6 if tier == LicenseTier.PRO else 1)
        prop_guard = (tier == LicenseTier.PROP_FIRM)
        telegram_alerts = (tier in (LicenseTier.PRO, LicenseTier.PROP_FIRM))

        days_left = max(0, int((expire_ts - time.time()) / 86400))
        info = {
            "valid": True,
            "tier": tier,
            "max_pairs": max_pairs,
            "prop_guard": prop_guard,
            "telegram_alerts": telegram_alerts,
            "days_remaining": days_left,
            "message": f"Active {tier} License ({days_left} Days Remaining)"
        }
        self.cached_info = info
        return info
