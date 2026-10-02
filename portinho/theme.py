"""Tema escuro, plano e arredondado."""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

ACCENT = "#7c5cff"
VIDEO = "#38bdf8"
MUSIC = "#f59e0b"

QSS = f"""
* {{ outline: none; }}
QWidget {{ color: #e8eaf0; font-size: 13px; }}
QMainWindow, #root {{ background: #0d0f14; }}
QToolTip {{ background: #1f232c; color: #e8eaf0; border: 1px solid #2f3542; padding: 6px 8px; border-radius: 6px; }}

#title {{ font-size: 20px; font-weight: 700; }}
#subtitle {{ color: #8b93a7; }}
#muted {{ color: #8b93a7; }}
#hint {{ color: #6b7386; font-size: 12px; }}

#card {{ background: #151820; border: 1px solid #222733; border-radius: 14px; }}
#card[dragOver="true"] {{ border: 2px dashed {ACCENT}; background: #1a1830; }}
#card[done="true"] {{ border: 1px solid #2b3445; }}
#step {{ background: #222733; color: #c9cfdb; border-radius: 11px; font-weight: 700;
         min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }}
#step[done="true"] {{ background: #16a34a; color: white; }}
#cardTitle {{ font-size: 14px; font-weight: 600; }}

#dropzone {{ background: #11131a; border: 1.5px dashed #2f3542; border-radius: 10px;
            color: #8b93a7; padding: 10px; text-align: center; }}
#dropzone[done="true"] {{ border: 1.5px solid #5c4313; color: #f6c76a; background: #17140f; }}
#dropzone:hover {{ border-color: {MUSIC}; color: #e8eaf0; background: #17140f; }}

QLineEdit {{ background: #0f1117; border: 1px solid #2a2f3a; border-radius: 9px;
            padding: 8px 10px; selection-background-color: {ACCENT}; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}

QPushButton {{ background: #222733; border: 1px solid #2c3240; border-radius: 9px;
              padding: 8px 14px; font-weight: 600; }}
QPushButton:hover {{ background: #2a3040; border-color: #3a4152; }}
QPushButton:pressed {{ background: #1b1f29; }}
QPushButton:disabled {{ color: #5a6173; background: #181b22; border-color: #20242e; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton#primary:hover {{ background: #8d72ff; }}
QPushButton#primary:disabled {{ background: #2a2550; border-color: #2a2550; color: #8b84b8; }}
QPushButton#ghost {{ background: transparent; border: none; color: #8b93a7; padding: 4px 8px; }}
QPushButton#ghost:hover {{ color: #e8eaf0; }}
QPushButton#icon {{ padding: 6px 10px; min-width: 18px; }}
QPushButton#play {{ background: white; color: #0d0f14; border: none; border-radius: 23px;
                   min-width: 46px; max-width: 46px; min-height: 46px; max-height: 46px;
                   font-size: 18px; padding: 0; }}
QPushButton#play:hover {{ background: #e6e6ef; }}
QPushButton#play:disabled {{ background: #2a2f3a; color: #5a6173; }}

QDoubleSpinBox {{ background: #0f1117; border: 1px solid #2a2f3a; border-radius: 9px;
                 padding: 6px 8px; font-weight: 600; font-size: 14px; min-width: 96px; }}
QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QSlider::groove:horizontal {{ height: 4px; background: #2a2f3a; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: #c9cfdb; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

QProgressBar {{ background: #1b1f29; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QSplitter::handle {{ background: transparent; height: 8px; }}
#videoBox {{ background: #000; border-radius: 14px; }}
#placeholder {{ color: #5a6173; font-size: 15px; }}
#time {{ font-size: 15px; font-weight: 600; font-family: "JetBrains Mono", "Consolas", "DejaVu Sans Mono", monospace; }}
#toast {{ background: #1f232c; border: 1px solid #2f3542; border-radius: 10px; padding: 10px 14px; }}
"""


def apply(app):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, c in ((QPalette.Window, "#0d0f14"), (QPalette.WindowText, "#e8eaf0"),
                    (QPalette.Base, "#0f1117"), (QPalette.AlternateBase, "#151820"),
                    (QPalette.Text, "#e8eaf0"), (QPalette.Button, "#222733"),
                    (QPalette.ButtonText, "#e8eaf0"), (QPalette.Highlight, ACCENT),
                    (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#1f232c"),
                    (QPalette.ToolTipText, "#e8eaf0"), (QPalette.PlaceholderText, "#5a6173")):
        pal.setColor(role, QColor(c))
    app.setPalette(pal)
    installed = set(QFontDatabase.families())
    f = QFont()
    for fam in ("Inter", "Segoe UI Variable Text", "Segoe UI", "Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans"):
        if fam in installed:
            f.setFamily(fam)
            break
    f.setPointSizeF(10)
    app.setFont(f)
    app.setStyleSheet(QSS)
