"""
9altitudes Theme for Flet UI.
Based on 9altitudes brand colors and design.
"""

import flet as ft


class NineAltitudesTheme:
    """9altitudes brand theme colors and styling."""
    
    # Primary colors - based on 9altitudes website
    PRIMARY = "#1e3a5f"  # Deep navy blue
    PRIMARY_LIGHT = "#2d5a8a"  # Lighter blue
    PRIMARY_DARK = "#0f1f33"  # Darker navy
    
    # Accent colors
    ACCENT = "#f47920"  # Orange (from 9altitudes branding)
    ACCENT_LIGHT = "#ff9a4d"
    ACCENT_DARK = "#c55a00"
    
    # Secondary colors
    SECONDARY = "#6b7c93"  # Muted blue-gray
    SECONDARY_LIGHT = "#8fa1b8"
    
    # Background colors
    BACKGROUND = "#f8f9fa"  # Light gray background
    SURFACE = "#ffffff"  # White surface
    CARD = "#ffffff"
    
    # Text colors
    TEXT_PRIMARY = "#1e3a5f"  # Navy for headings
    TEXT_SECONDARY = "#6b7c93"  # Gray for body
    TEXT_ON_PRIMARY = "#ffffff"
    TEXT_ON_ACCENT = "#ffffff"
    
    # Status colors
    SUCCESS = "#28a745"
    WARNING = "#ffc107"
    ERROR = "#dc3545"
    INFO = "#17a2b8"
    
    # Border and divider
    BORDER = "#dee2e6"
    DIVIDER = "#e9ecef"
    
    @classmethod
    def get_theme(cls) -> ft.Theme:
        """Get the Flet theme configuration."""
        return ft.Theme(
            color_scheme_seed=ft.Colors.BLUE,
            color_scheme=ft.ColorScheme(
                primary=cls.PRIMARY,
                on_primary=cls.TEXT_ON_PRIMARY,
                secondary=cls.ACCENT,
                on_secondary=cls.TEXT_ON_ACCENT,
                surface=cls.SURFACE,
                on_surface=cls.TEXT_PRIMARY,
                background=cls.BACKGROUND,
                on_background=cls.TEXT_PRIMARY,
                error=cls.ERROR,
            ),
            font_family="Segoe UI",
            visual_density=ft.VisualDensity.COMFORTABLE,
        )
    
    @classmethod
    def get_dark_theme(cls) -> ft.Theme:
        """Get the dark theme configuration."""
        return ft.Theme(
            color_scheme_seed=ft.Colors.BLUE,
            color_scheme=ft.ColorScheme(
                primary=cls.PRIMARY_LIGHT,
                on_primary=cls.TEXT_ON_PRIMARY,
                secondary=cls.ACCENT,
                on_secondary=cls.TEXT_ON_ACCENT,
                surface="#1e1e1e",
                on_surface="#ffffff",
                background="#121212",
                on_background="#ffffff",
                error=cls.ERROR,
            ),
            font_family="Segoe UI",
            visual_density=ft.VisualDensity.COMFORTABLE,
        )
    
    @classmethod
    def styled_button(
        cls,
        text: str,
        on_click=None,
        icon=None,
        primary: bool = True,
        disabled: bool = False,
        expand: bool = False
    ) -> ft.ElevatedButton:
        """Create a styled button."""
        return ft.ElevatedButton(
            text=text,
            icon=icon,
            on_click=on_click,
            disabled=disabled,
            expand=expand,
            style=ft.ButtonStyle(
                color=cls.TEXT_ON_PRIMARY if primary else cls.PRIMARY,
                bgcolor=cls.PRIMARY if primary else cls.SURFACE,
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                shape=ft.RoundedRectangleBorder(radius=8),
                elevation=2 if primary else 0,
            )
        )
    
    @classmethod
    def accent_button(
        cls,
        text: str,
        on_click=None,
        icon=None,
        disabled: bool = False,
        expand: bool = False
    ) -> ft.ElevatedButton:
        """Create an accent-colored button."""
        return ft.ElevatedButton(
            text=text,
            icon=icon,
            on_click=on_click,
            disabled=disabled,
            expand=expand,
            style=ft.ButtonStyle(
                color=cls.TEXT_ON_ACCENT,
                bgcolor=cls.ACCENT,
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                shape=ft.RoundedRectangleBorder(radius=8),
                elevation=2,
            )
        )
    
    @classmethod
    def styled_card(cls, content: ft.Control, padding: int = 20) -> ft.Container:
        """Create a styled card container."""
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor=cls.CARD,
            border_radius=12,
            border=ft.border.all(1, cls.BORDER),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.1, ft.Colors.BLACK),
                offset=ft.Offset(0, 2)
            )
        )
    
    @classmethod
    def section_title(cls, text: str, icon=None) -> ft.Row:
        """Create a section title."""
        controls = []
        if icon:
            controls.append(ft.Icon(icon, color=cls.PRIMARY, size=24))
        controls.append(
            ft.Text(
                text,
                size=18,
                weight=ft.FontWeight.BOLD,
                color=cls.TEXT_PRIMARY
            )
        )
        return ft.Row(controls, spacing=10)
    
    @classmethod
    def status_badge(cls, text: str, status: str = "info") -> ft.Container:
        """Create a status badge."""
        colors = {
            "success": cls.SUCCESS,
            "warning": cls.WARNING,
            "error": cls.ERROR,
            "info": cls.INFO,
        }
        bg_color = colors.get(status, cls.INFO)
        
        return ft.Container(
            content=ft.Text(text, size=12, color=ft.Colors.WHITE),
            bgcolor=bg_color,
            padding=ft.padding.symmetric(horizontal=12, vertical=4),
            border_radius=20,
        )
    
    # Input text color (black for visibility)
    TEXT_INPUT = "#000000"  # Black for input text
    
    @classmethod
    def styled_textfield(
        cls,
        label: str,
        hint_text: str = "",
        value: str = "",
        password: bool = False,
        multiline: bool = False,
        on_change=None,
        icon=None,
        disabled: bool = False
    ) -> ft.TextField:
        """Create a styled text field with black text for visibility."""
        return ft.TextField(
            label=label,
            hint_text=hint_text,
            value=value,
            password=password,
            can_reveal_password=password,
            multiline=multiline,
            min_lines=3 if multiline else 1,
            max_lines=10 if multiline else 1,
            on_change=on_change,
            prefix_icon=icon,
            disabled=disabled,
            border_color=cls.BORDER,
            focused_border_color=cls.PRIMARY,
            cursor_color=cls.PRIMARY,
            border_radius=8,
            color=cls.TEXT_INPUT,  # Black text for entered values
            text_style=ft.TextStyle(
                color=cls.TEXT_INPUT,
                weight=ft.FontWeight.NORMAL,
            ),
            label_style=ft.TextStyle(
                color=cls.TEXT_SECONDARY,
            ),
            hint_style=ft.TextStyle(
                color=cls.SECONDARY,
            ),
        )
    
    @classmethod
    def styled_dropdown(
        cls,
        label: str,
        options: list,
        value: str = None,
        on_change=None,
        disabled: bool = False
    ) -> ft.Dropdown:
        """Create a styled dropdown."""
        return ft.Dropdown(
            label=label,
            value=value,
            options=[ft.dropdown.Option(key=o, text=o) for o in options],
            on_change=on_change,
            disabled=disabled,
            border_color=cls.BORDER,
            focused_border_color=cls.PRIMARY,
            border_radius=8,
        )
    
    @classmethod
    def header_bar(cls, title: str, subtitle: str = None) -> ft.Container:
        """Create a header bar."""
        content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.PLAY_CIRCLE_FILLED, color=cls.ACCENT, size=32),
                        ft.Text(
                            title,
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color=cls.TEXT_ON_PRIMARY
                        ),
                    ],
                    spacing=12,
                ),
            ],
            spacing=4,
        )
        
        if subtitle:
            content.controls.append(
                ft.Text(
                    subtitle,
                    size=14,
                    color=ft.Colors.with_opacity(0.8, cls.TEXT_ON_PRIMARY)
                )
            )
        
        return ft.Container(
            content=content,
            padding=ft.padding.symmetric(horizontal=24, vertical=16),
            bgcolor=cls.PRIMARY,
            gradient=ft.LinearGradient(
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
                colors=[cls.PRIMARY, cls.PRIMARY_LIGHT]
            ),
        )


# Convenience exports
theme = NineAltitudesTheme
