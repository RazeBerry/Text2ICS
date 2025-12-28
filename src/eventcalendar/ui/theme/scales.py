"""Typography and spacing scales for the design system.

Anthropic-Inspired Design System
================================
Typography uses a refined serif/sans-serif pairing for editorial warmth.
Spacing follows a harmonious scale with generous whitespace.
"""

# Typography Scale
# Primary: Georgia or system serif for warmth and readability
# Secondary: SF Pro or system sans for UI elements
# The combination evokes thoughtfulness and precision

TYPOGRAPHY_SCALE = {
    "display": {
        "size_px": 36,
        "weight": 400,
        "line_height": 1.15,
        "letter_spacing": "-0.02em",
        "font_family": "Georgia, 'Times New Roman', serif",
    },
    "title": {
        "size_px": 26,
        "weight": 400,
        "line_height": 1.2,
        "letter_spacing": "-0.01em",
        "font_family": "Georgia, 'Times New Roman', serif",
    },
    "headline": {
        "size_px": 18,
        "weight": 500,
        "line_height": 1.35,
        "letter_spacing": "0",
        "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    },
    "body": {
        "size_px": 15,
        "weight": 400,
        "line_height": 1.5,
        "letter_spacing": "0",
        "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    },
    "body_serif": {
        "size_px": 15,
        "weight": 400,
        "line_height": 1.6,
        "letter_spacing": "0.01em",
        "font_family": "Georgia, 'Times New Roman', serif",
    },
    "caption": {
        "size_px": 13,
        "weight": 400,
        "line_height": 1.4,
        "letter_spacing": "0.01em",
        "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    },
    "footnote": {
        "size_px": 11,
        "weight": 400,
        "line_height": 1.3,
        "letter_spacing": "0.02em",
        "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    },
    "label": {
        "size_px": 12,
        "weight": 600,
        "line_height": 1.2,
        "letter_spacing": "0.05em",
        "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    },
    "mono": {
        "size_px": 14,
        "weight": 400,
        "line_height": 1.5,
        "letter_spacing": "0",
        "font_family": "'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace",
    },
}

# Spacing Scale - generous and harmonious
# Based on 8px base unit with refined increments
SPACING_SCALE = {
    "xxs": 4,
    "xs": 8,
    "sm": 16,
    "md": 24,
    "lg": 32,
    "xl": 48,
    "xxl": 64,
    "xxxl": 96,
}

# Border Radius - soft but not overly rounded
BORDER_RADIUS = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "full": 9999,  # For pills and circles
}

# Shadow Scale - warm-tinted shadows for depth
SHADOW_SCALE = {
    "sm": "0 1px 2px rgba(45, 41, 38, 0.05)",
    "md": "0 4px 12px rgba(45, 41, 38, 0.08)",
    "lg": "0 8px 24px rgba(45, 41, 38, 0.12)",
    "xl": "0 16px 48px rgba(45, 41, 38, 0.16)",
    "inner": "inset 0 1px 2px rgba(45, 41, 38, 0.06)",
    "glow": "0 0 24px rgba(204, 90, 71, 0.2)",  # Terracotta glow
}

# Transition durations
TRANSITIONS = {
    "fast": "120ms",
    "normal": "200ms",
    "slow": "350ms",
    "spring": "400ms cubic-bezier(0.34, 1.56, 0.64, 1)",
}
