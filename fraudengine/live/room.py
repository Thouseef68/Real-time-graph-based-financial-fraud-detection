"""Room model and state management for Live Sandbox Bank with hardened security and privacy."""

from __future__ import annotations

import logging
import random
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from fraudengine.live.clock import CompressedClock
from fraudengine.live.recorder import SessionRecorder
from fraudengine.live.security import generate_session_token, generate_join_token, truncate_ip

logger = logging.getLogger(__name__)

# Scripted role cards for real network & device topology scenario (Item 16)
DEFAULT_ROLE_CARDS = [
    {
        "role_id": "VICTIM_1",
        "title": "Victim 1 (Urgent Payment Scam)",
        "badge": "Victim",
        "instructions": "You received an urgent SMS requesting payment. Send ₹2,500 to Member A.",
        "suggested_target": "MEMBER_A",
        "suggested_amount": 2500.0,
        "network_hint": "Any network (Wi-Fi or Mobile Data)",
    },
    {
        "role_id": "VICTIM_2",
        "title": "Victim 2 (Phishing Target)",
        "badge": "Victim",
        "instructions": "Transfer ₹3,000 to Member A for an alleged utility invoice refund.",
        "suggested_target": "MEMBER_A",
        "suggested_amount": 3000.0,
        "network_hint": "Any network",
    },
    {
        "role_id": "MEMBER_A",
        "title": "Member A (Mule Accumulator)",
        "badge": "Mule Accumulator",
        "instructions": "Connect to Campus Wi-Fi. Wait for victim deposits, then forward ₹5,000 to Member B immediately.",
        "suggested_target": "MEMBER_B",
        "suggested_amount": 5000.0,
        "network_hint": "Campus Wi-Fi (shared with Member B)",
    },
    {
        "role_id": "MEMBER_B",
        "title": "Member B (Layering Hop 1)",
        "badge": "Layering Peer",
        "instructions": "Connect to Campus Wi-Fi. Once funds arrive from Member A, forward ₹4,500 to Member C. Hand your phone to Member C when prompted.",
        "suggested_target": "MEMBER_C",
        "suggested_amount": 4500.0,
        "network_hint": "Campus Wi-Fi (shares phone with Member C)",
    },
    {
        "role_id": "MEMBER_C",
        "title": "Member C (Shared Device Ring Node)",
        "badge": "Shared Device Node",
        "instructions": "Log into Member B's phone using the Account Switcher (creating a genuine shared-device graph link), then forward ₹4,000 to Member D.",
        "suggested_target": "MEMBER_D",
        "suggested_amount": 4000.0,
        "network_hint": "Logs into Member B's phone (Shared Device)",
    },
    {
        "role_id": "MEMBER_D",
        "title": "Member D (Cash-Out on Mobile Data)",
        "badge": "Cash-Out Peer",
        "instructions": "Stay on Cellular Mobile Data (distinct IP prefix). Attempt to cash out ₹3,500 to the external Crypto OTC bot.",
        "suggested_target": "BOT_CRYPTO_EXCHANGE",
        "suggested_amount": 3500.0,
        "network_hint": "Mobile Data (Distinct IP prefix)",
    },
    {
        "role_id": "NORMAL_NEIGHBOR",
        "title": "Innocent Bystander (Clean Account)",
        "badge": "Normal Customer",
        "instructions": "You are on Campus Wi-Fi. Buy lunch by sending ₹250 to Campus Mart. Your payment passes cleanly.",
        "suggested_target": "BOT_MERCHANT_CAMPUS_MART",
        "suggested_amount": 250.0,
        "network_hint": "Campus Wi-Fi",
    },
]

BACKGROUND_BOTS = [
    {
        "account_id": "BOT_MERCHANT_CAMPUS_MART",
        "display_name": "Campus Mart (Merchant)",
        "balance": 150000.0,
        "device_id": "DEV_BOT_CAMPUS_MART",
        "raw_ip": "10.0.1.5",
        "network_label": "Campus-Retail",
        "is_bot": True,
    },
    {
        "account_id": "BOT_CRYPTO_EXCHANGE",
        "display_name": "Apex Crypto OTC (Exchange)",
        "balance": 500000.0,
        "device_id": "DEV_BOT_CRYPTO_OTC",
        "raw_ip": "198.51.100.99",
        "network_label": "External-Offramp",
        "is_bot": True,
    },
    {
        "account_id": "BOT_USER_RAHUL",
        "display_name": "Rahul (Bot Peer)",
        "balance": 12000.0,
        "device_id": "DEV_BOT_RAHUL",
        "raw_ip": "10.0.1.22",
        "network_label": "Student-Dorm",
        "is_bot": True,
    },
]


@dataclass
class Participant:
    account_id: str
    display_name: str
    balance: float
    device_id: str
    user_agent: str
    network_prefix: str  # /24 or /64 prefix - raw IP is never stored
    masked_ip: str       # e.g. 103.45.67.x
    network_label: str
    joined_at: float
    session_token: str
    consent_timestamp: float
    coarse_fingerprint: str = ""
    is_bot: bool = False
    role_card: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Full participant record for analyst console."""
        d = asdict(self)
        # Omit raw session token in general broadcasts unless needed
        return d

    def to_public_recipient_dict(self) -> Dict[str, Any]:
        """Safe view for public participants: display name only, never other balances."""
        return {
            "account_id": self.account_id,
            "display_name": self.display_name,
            "is_bot": self.is_bot,
        }

    def to_me_dict(self) -> Dict[str, Any]:
        """Safe view for the participant's own customer app view."""
        return {
            "account_id": self.account_id,
            "display_name": self.display_name,
            "balance": round(self.balance, 2),
            "device_id": self.device_id[:12],
            "network_prefix": self.network_prefix,
            "masked_ip": self.masked_ip,
            "role_card": self.role_card,
            "consent_timestamp": self.consent_timestamp,
        }


class SandboxRoom:
    """Encapsulates all real-time state for an interactive live demo room."""

    def __init__(
        self,
        room_code: str,
        scale_factor: float = 60.0,
        starting_balance: float = 10000.0,
        ttl_seconds: float = 7200.0,
        join_token: Optional[str] = None,
        max_participants: int = 50,
        max_transfer_amount: float = 50000.0,
    ):
        self.room_code = str(room_code).upper()
        self.created_at = time.time()
        self.expires_at = self.created_at + ttl_seconds
        self.starting_balance = float(starting_balance)
        self.join_token = join_token or generate_join_token()
        self.max_participants = max_participants
        self.max_transfer_amount = max_transfer_amount
        self.clock = CompressedClock(scale_factor=scale_factor, base_sim_step=700)
        self.recorder = SessionRecorder(room_code=self.room_code)

        # Participants store: account_id -> Participant
        self.participants: Dict[str, Participant] = {}
        # Token index: session_token -> account_id
        self.token_to_account: Dict[str, str] = {}

        # Ledgers & metrics
        self.transfers: List[Dict[str, Any]] = []
        self.money_moved = 0.0
        self.money_held = 0.0
        self.money_saved = 0.0

        # Idempotency and rate limiting
        self._idempotency_cache: Dict[str, Dict[str, Any]] = {}
        self._token_rate_limits: Dict[str, List[float]] = {}
        self._prefix_rate_limits: Dict[str, List[float]] = {}

        # Analyst Case Queue
        self.case_queue: Dict[str, Dict[str, Any]] = {}

        # Initialize background bots
        self._init_bots()

    def _init_bots(self) -> None:
        for bot_info in BACKGROUND_BOTS:
            prefix, masked = truncate_ip(bot_info["raw_ip"])
            bot = Participant(
                account_id=bot_info["account_id"],
                display_name=bot_info["display_name"],
                balance=bot_info["balance"],
                device_id=bot_info["device_id"],
                user_agent="FraudEngine-Bot/2.0",
                network_prefix=prefix,
                masked_ip=masked,
                network_label=bot_info["network_label"],
                joined_at=self.created_at,
                session_token=f"BOT_TOKEN_{bot_info['account_id']}",
                consent_timestamp=self.created_at,
                is_bot=True,
            )
            self.participants[bot.account_id] = bot
            self.token_to_account[bot.session_token] = bot.account_id

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def add_participant(
        self,
        display_name: str,
        device_id: str = "",
        user_agent: str = "Mozilla/5.0",
        raw_ip: str = "127.0.0.1",
        network_label: str = "Campus-WiFi",
        coarse_fingerprint: str = "",
        consent_accepted: bool = True,
        network_prefix: Optional[str] = None,
        masked_ip: Optional[str] = None,
    ) -> Participant:
        if len([p for p in self.participants.values() if not p.is_bot]) >= self.max_participants:
            raise ValueError(f"Room {self.room_code} has reached its maximum capacity of {self.max_participants} participants.")

        clean_name = "".join(c for c in display_name if c.isalnum())[:10].upper()
        uid = uuid.uuid4().hex[:4].upper()
        account_id = f"CUST_{clean_name}_{uid}"

        # Assign available scripted role card
        assigned_role = None
        used_roles = {p.role_card["role_id"] for p in self.participants.values() if p.role_card}
        for card in DEFAULT_ROLE_CARDS:
            if card["role_id"] not in used_roles:
                assigned_role = card
                break

        # Truncate IP immediately and discard raw IP unless explicitly provided
        if network_prefix and masked_ip:
            net_prefix = network_prefix
            mask_ip = masked_ip
        else:
            net_prefix, mask_ip = truncate_ip(raw_ip)
        session_token = generate_session_token()
        consent_ts = time.time()

        participant = Participant(
            account_id=account_id,
            display_name=display_name.strip() or f"User-{uid}",
            balance=self.starting_balance,
            device_id=device_id or f"DEV_BROWSER_{uid}",
            user_agent=user_agent or "Unknown Browser",
            network_prefix=net_prefix,
            masked_ip=mask_ip,
            network_label=network_label or "Campus-WiFi",
            joined_at=consent_ts,
            session_token=session_token,
            consent_timestamp=consent_ts,
            coarse_fingerprint=coarse_fingerprint,
            is_bot=False,
            role_card=assigned_role,
        )
        self.participants[account_id] = participant
        self.token_to_account[session_token] = account_id

        self.recorder.record_event("participant_joined", {
            "account_id": participant.account_id,
            "display_name": participant.display_name,
            "masked_ip": participant.masked_ip,
            "network_prefix": participant.network_prefix,
            "device_id": participant.device_id,
            "role_card": assigned_role,
        })
        return participant

    def get_participant(self, account_id: str) -> Optional[Participant]:
        return self.participants.get(account_id)

    def get_participant_by_token(self, token: str) -> Optional[Participant]:
        account_id = self.token_to_account.get(token)
        if account_id:
            return self.participants.get(account_id)
        return None

    def update_network_label(self, account_id: str, new_label: str) -> bool:
        if account_id in self.participants:
            self.participants[account_id].network_label = new_label
            self.recorder.record_event("network_label_updated", {"account_id": account_id, "new_label": new_label})
            return True
        return False

    def check_rate_limits(self, session_token: str, network_prefix: str) -> Tuple[bool, str]:
        """Check rate limits per token (5 txns / 10s) and per prefix (30 txns / 60s)."""
        now = time.time()

        # 1. Token limit
        token_timestamps = self._token_rate_limits.setdefault(session_token, [])
        self._token_rate_limits[session_token] = [t for t in token_timestamps if now - t <= 10.0]
        if len(self._token_rate_limits[session_token]) >= 5:
            return False, "Rate limit exceeded for your account (maximum 5 transfers per 10 seconds)."

        # 2. Network prefix limit
        prefix_timestamps = self._prefix_rate_limits.setdefault(network_prefix, [])
        self._prefix_rate_limits[network_prefix] = [t for t in prefix_timestamps if now - t <= 60.0]
        if len(self._prefix_rate_limits[network_prefix]) >= 30:
            return False, "Rate limit exceeded for this network prefix (maximum 30 transfers per minute)."

        self._token_rate_limits[session_token].append(now)
        self._prefix_rate_limits[network_prefix].append(now)
        return True, ""

    def check_idempotency(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        return self._idempotency_cache.get(idempotency_key)

    def record_idempotency(self, idempotency_key: str, response: Dict[str, Any]) -> None:
        self._idempotency_cache[idempotency_key] = response

    def add_case_to_queue(self, case_id: str, case_data: Dict[str, Any]) -> None:
        case_data["case_id"] = case_id
        case_data["created_at"] = time.time()
        case_data["status"] = "PENDING"
        self.case_queue[case_id] = case_data

    def to_dict(self) -> Dict[str, Any]:
        """Full representation for local analyst console."""
        return {
            "room_code": self.room_code,
            "join_token": self.join_token,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "max_participants": self.max_participants,
            "max_transfer_amount": self.max_transfer_amount,
            "clock": self.clock.to_dict(),
            "participants_count": len([p for p in self.participants.values() if not p.is_bot]),
            "bots_count": len([p for p in self.participants.values() if p.is_bot]),
            "participants": [p.to_dict() for p in self.participants.values()],
            "money_moved": round(self.money_moved, 2),
            "money_held": round(self.money_held, 2),
            "money_saved": round(self.money_saved, 2),
            "transfers_count": len(self.transfers),
            "recent_transfers": self.transfers[-30:],
            "pending_cases_count": len([c for c in self.case_queue.values() if c["status"] == "PENDING"]),
        }
