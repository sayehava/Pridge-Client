# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class JobHistoryEntry:
    job_id: str
    status: str
    detail: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
