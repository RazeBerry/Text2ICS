"""Color palettes for light and dark themes.

Anthropic-Inspired Design System
================================
A warm, sophisticated palette that feels premium and thoughtfully crafted.
Inspired by natural materials: terracotta, sand, slate, and aged paper.
"""

# Anthropic Design System - Warm Terracotta & Sand Palette
# Evokes: Mediterranean warmth, architectural precision, Claude's thoughtfulness

LIGHT_PALETTE = {
    # Text hierarchy - warm slate tones
    "text_primary": "#2D2926",       # Warm charcoal, not pure black
    "text_secondary": "#6B625A",     # Warm medium gray
    "text_tertiary": "#9A918A",      # Muted warm gray
    "text_placeholder": "#B8AFA8",   # Subtle placeholder

    # Backgrounds - aged paper and sand
    "background_primary": "#FDFBF7",   # Warm off-white, like aged paper
    "background_secondary": "#F7F4EE", # Light sand
    "background_tertiary": "#F0EBE3",  # Warm cream

    # Borders - subtle warmth
    "border_light": "#E8E2D9",       # Soft sand border
    "border_medium": "#D4CCC2",      # Warm stone border

    # Accent - Anthropic terracotta/coral
    "accent": "#CC5A47",             # Terracotta coral - the signature
    "accent_hover": "#B8483A",       # Deeper terracotta
    "accent_pressed": "#A03C2E",     # Rich rust
    "accent_disabled": "#D9CFC6",    # Muted sand

    # Accent secondary - warm amber
    "accent_secondary": "#C17F3C",   # Warm amber/gold
    "accent_secondary_hover": "#A66B2D",

    # Status colors - warm-shifted
    "success": "#4A7C59",            # Sage green
    "warning": "#C17F3C",            # Warm amber
    "error": "#B8483A",              # Muted red-terracotta

    # Special surfaces
    "surface_elevated": "#FFFFFF",   # Pure white for cards
    "surface_overlay": "rgba(45, 41, 38, 0.6)",  # Warm overlay

    # Decorative
    "glow_accent": "rgba(204, 90, 71, 0.15)",  # Terracotta glow
    "gradient_start": "#FDFBF7",
    "gradient_end": "#F7F4EE",
}

DARK_PALETTE = {
    # Text hierarchy - warm cream tones
    "text_primary": "#F5F2EC",       # Warm off-white
    "text_secondary": "#B8AFA8",     # Muted warm gray
    "text_tertiary": "#847B74",      # Subdued warm gray
    "text_placeholder": "#6B625A",   # Dark placeholder

    # Backgrounds - deep warm charcoal
    "background_primary": "#1E1B18",   # Warm near-black
    "background_secondary": "#252220", # Warm dark gray
    "background_tertiary": "#2E2A27",  # Elevated dark surface

    # Borders - subtle definition
    "border_light": "#3A3532",       # Warm dark border
    "border_medium": "#4A4440",      # Medium warm border

    # Accent - lighter terracotta for dark mode
    "accent": "#E07058",             # Bright terracotta
    "accent_hover": "#E88A74",       # Lighter terracotta
    "accent_pressed": "#CC5A47",     # Standard terracotta
    "accent_disabled": "#4A4440",    # Muted dark

    # Accent secondary
    "accent_secondary": "#D4924A",   # Warm amber
    "accent_secondary_hover": "#E0A45C",

    # Status colors
    "success": "#6B9B7A",            # Soft sage
    "warning": "#D4924A",            # Warm amber
    "error": "#E07058",              # Bright terracotta

    # Special surfaces
    "surface_elevated": "#2E2A27",   # Elevated surface
    "surface_overlay": "rgba(0, 0, 0, 0.7)",  # Dark overlay

    # Decorative
    "glow_accent": "rgba(224, 112, 88, 0.2)",  # Terracotta glow
    "gradient_start": "#1E1B18",
    "gradient_end": "#252220",
}
