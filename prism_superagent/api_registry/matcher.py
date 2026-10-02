"""Deterministic, slot-aware matching for the deliberately small API surface."""

import re

SUPPORTED_CAPABILITIES = ("book_search", "currency_rate", "geocoding")


class RegistryMatcher:
    def match(self, request, registry):
        if not isinstance(request, str) or not request.strip() or len(request) > 20_000:
            return None
        text = request.strip()
        capability, params, evidence, confidence = self._intent(text)
        if not capability or capability not in SUPPORTED_CAPABILITIES:
            return None
        providers = registry.candidates(capability, configured_only=True)
        if not providers:
            return None
        explanation = (
            f"Matched '{evidence}' to the {capability} capability; "
            f"required request slots are present. Candidate order is based on "
            f"reviewed provider priority and health."
        )
        return {
            "capability": capability,
            "parameters": params,
            "provider_ids": tuple(provider.provider_id for provider in providers),
            "confidence": confidence,
            "explanation": explanation,
        }

    @staticmethod
    def _intent(text):
        lower = text.casefold()
        currency = re.search(
            r"\b([a-z]{3})\s*(?:to|into|/)\s*([a-z]{3})\b", text, re.IGNORECASE
        )
        if currency and re.search(r"\b(exchange|currency|convert|rate)\b", lower):
            base, quote = currency.group(1).upper(), currency.group(2).upper()
            amount_match = re.search(
                r"\b([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s+"
                + re.escape(base)
                + r"\b",
                text,
                re.IGNORECASE,
            )
            params = {"base": base, "quote": quote}
            if amount_match:
                params["amount"] = amount_match.group(1).replace(",", "")
            return "currency_rate", params, currency.group(0), 0.97

        book_patterns = (
            (
                r"\b(?:find|search(?:\s+for)?|look\s+up)\s+(?:some\s+)?books?\s+"
                r"(?:about|on|by|written\s+by)\s+(.+)"
            ),
            r"\bbooks?\s+(?:about|on|by|written\s+by)\s+(.+)",
            r"\bsearch\s+open\s+library\s+(?:for\s+)?(.+)",
        )
        for pattern in book_patterns:
            found = re.search(pattern, text, re.IGNORECASE)
            if found:
                query = _clean_slot(found.group(1))
                if query:
                    return "book_search", {"q": query}, found.group(0)[:120], 0.94

        geo_patterns = (
            r"\b(?:get\s+)?coordinates\s+for\s+(.+)",
            r"\bgeocode\s+(.+)",
            r"\bfind\s+(?:the\s+)?coordinates\s+of\s+(.+)",
        )
        for pattern in geo_patterns:
            found = re.search(pattern, text, re.IGNORECASE)
            if found:
                name = _clean_slot(found.group(1))
                if name:
                    return "geocoding", {"name": name}, found.group(0)[:120], 0.96
        return None, {}, "", 0.0


def _clean_slot(value):
    value = value.strip().strip(" \t\r\n\"'`.,!?;:")
    value = re.sub(r"^(?:please\s+)?(?:for|of)\s+", "", value, flags=re.IGNORECASE)
    return value[:200].strip()
