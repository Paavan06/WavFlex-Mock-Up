"""
WavFlex Product Tagging — UI mock (standalone app, separate from WavFlex)

Run:  .venv\\Scripts\\python.exe main.py
"""

import flet as ft

from product_tagging import ProductTaggingView

HEADER_BG = "#827676"   # same header colour as WavFlex
PAGE_BG = "#F3F1ED"     # same warm background as WavFlex


def main(page: ft.Page):
    page.title = "WavFlex — Product Tagging (Mock)"
    page.bgcolor = PAGE_BG
    page.padding = 0
    page.window.width = 1280
    page.window.height = 860
    page.theme_mode = ft.ThemeMode.LIGHT

    header = ft.Container(
        bgcolor=HEADER_BG,
        height=96,
        padding=ft.padding.symmetric(horizontal=28),
        content=ft.Row(
            [
                # The logo PNG has lots of transparent padding, so crop it a bit
                ft.Container(
                    width=180,
                    height=96,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    content=ft.Image(
                        src="wavflex.png", fit=ft.ImageFit.COVER, scale=2.2
                    ),
                ),
                ft.Text(
                    "Product Tagging",
                    size=18,
                    color="#F3F1ED",
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    view = ProductTaggingView(page)

    page.add(
        ft.Column(
            [
                header,
                ft.Container(
                    expand=True,
                    padding=20,
                    content=ft.Column([view.build()], scroll=ft.ScrollMode.AUTO),
                ),
            ],
            spacing=0,
            expand=True,
        )
    )


if __name__ == "__main__":
    ft.app(target=main, assets_dir="assets")
