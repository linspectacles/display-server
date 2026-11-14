#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# LinSpectacles - Linux Inspection Suite
# Copyright (C) 2026 brunonlinespace
# GPL-3.0-or-later
"""Display Server; Kernel Modules 0.0.5 authoritative shell."""

APPLET_ID = 'linspectacles-display-server'
APPLET_NAME = 'Display Server'
APPLET_VERSION = '0.0.6'
APPLET_AUTHOR = 'brunonlinespace'
APPLET_EDITOR = 'brunonlinespace'

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, QTimer, QUrl, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QPixmap, QShortcut, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QTabWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from ._support import (
    BaseInspectorTab, ColumnVisibilityController, export_records_dialog,
    metadata_font_qss,
)
from .collectors import VIEWS, COLUMNS, collect_snapshot, inventory_sort_key

SETTINGS_NAME = 'Display Server'
REPOSITORY_URL = 'https://github.com/linspectacles/display-server'
ORGANISATION_URL = 'https://github.com/linspectacles/'


def _flat(value):
    if value is None:
        return 'Not exposed'
    if isinstance(value, dict):
        return ', '.join(f'{key}={entry}' for key, entry in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return ', '.join(str(entry) for entry in value)
    return str(value)


def _view_columns(view):
    """Map the fixed collector schema into the authoritative table schema."""
    right_aligned = {'pid'}
    return [
        (key, title, 115 if key in right_aligned else 160,
         'right' if key in right_aligned else 'left')
        for key, title in COLUMNS[view]
    ]


class DisplayServerOptionsDialog(QDialog):
    """Kernel Modules 0.0.5 Options surface, with applet-specific copy."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('Options — Display Server')
        self.resize(980, 720)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # Appearance — same structure, controls and spacing as Kernel Modules.
        appearance_page = QWidget()
        appearance_layout = QVBoxLayout(appearance_page)
        appearance_layout.setContentsMargins(12, 12, 12, 12)
        appearance_layout.setSpacing(10)

        appearance_heading = QLabel('Metadata display')
        heading_font = appearance_heading.font()
        heading_font.setBold(True)
        appearance_heading.setFont(heading_font)
        appearance_layout.addWidget(appearance_heading)

        appearance_note = QLabel(
            'Choose how the inventory and Metadata Details panes are arranged. '
            'This Display Server setting is remembered.'
        )
        appearance_note.setWordWrap(True)
        appearance_layout.addWidget(appearance_note)

        layout_row = QHBoxLayout()
        layout_row.addWidget(QLabel('Record details layout:'))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(['Horizontal', 'Vertical'])
        self.layout_combo.setCurrentText(
            'Vertical' if owner.details_orientation == 'vertical' else 'Horizontal'
        )
        self.layout_combo.currentTextChanged.connect(self._layout_changed)
        layout_row.addWidget(self.layout_combo)
        layout_row.addStretch(1)
        appearance_layout.addLayout(layout_row)

        self.show_metadata_panel = QCheckBox('Show Metadata Details panel (F3)')
        self.show_metadata_panel.setChecked(owner.metadata_panel_visible)
        self.show_metadata_panel.toggled.connect(self._metadata_panel_changed)
        appearance_layout.addWidget(self.show_metadata_panel)

        shortcut_note = QLabel(
            'F3 hides/restores Metadata Details. Shift+F5 refreshes the display inventory. '
            'Ctrl+L toggles Horizontal/Vertical layout. Ctrl+/ opens Options. '
            'View: Ctrl+1 = Session; Ctrl+2 = Display Stack; Ctrl+3 = Outputs; '
            'Ctrl+4 = Modes; Ctrl+5 = Protocols.'
        )
        shortcut_note.setWordWrap(True)
        appearance_layout.addWidget(shortcut_note)
        appearance_layout.addStretch(1)
        tabs.addTab(appearance_page, 'Appearance')

        # Sources — exact Kernel Modules QTextEdit treatment and cursor formatting.
        sources_page = QWidget()
        sources_layout = QVBoxLayout(sources_page)
        sources_layout.setContentsMargins(12, 12, 12, 12)
        sources_layout.setSpacing(10)
        sources_heading = QLabel('Data Sources')
        sources_heading_font = sources_heading.font()
        sources_heading_font.setBold(True)
        sources_heading_font.setPointSize(max(sources_heading_font.pointSize(), 11))
        sources_heading.setFont(sources_heading_font)
        sources_layout.addWidget(sources_heading)

        sources_note = QLabel('Linux interfaces used by this read-only display-server applet.')
        sources_note.setWordWrap(True)
        sources_layout.addWidget(sources_note)

        sources_text = QTextEdit()
        sources_text.setReadOnly(True)
        sources_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        chosen_font = getattr(owner, '_metadata_font', None)
        if chosen_font is not None:
            sources_text.setFont(chosen_font)
            sources_text.document().setDefaultFont(chosen_font)
            sources_text.setCurrentFont(chosen_font)
            font_rule = metadata_font_qss(chosen_font)
        else:
            font_rule = ''
        sources_text.setStyleSheet(
            'QTextEdit { '
            + font_rule
            + ' background-color: #151719; color: #dcdcdc; '
              'border: 1px solid #333333; }'
        )
        source_key_format = QTextCharFormat()
        source_key_format.setForeground(QColor('#9cdcfe'))
        source_key_format.setFontWeight(600)
        source_value_format = QTextCharFormat()
        source_value_format.setForeground(QColor('#dcdcdc'))
        cursor = sources_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for line in owner.sources_text().splitlines():
            if line and not line[:1].isspace():
                cursor.insertText(line + '\n', source_key_format)
            else:
                cursor.insertText(line + '\n', source_value_format)
        sources_text.setTextCursor(cursor)
        sources_text.moveCursor(QTextCursor.MoveOperation.Start)
        sources_layout.addWidget(sources_text, 1)
        tabs.addTab(sources_page, 'Sources')

        # Export — same Kernel Modules checkbox layout, adapted to current view.
        export_page = QWidget()
        export_layout = QVBoxLayout(export_page)
        export_layout.setContentsMargins(12, 12, 12, 12)
        export_layout.setSpacing(10)
        export_heading = QLabel('Export details')
        export_heading_font = export_heading.font()
        export_heading_font.setBold(True)
        export_heading.setFont(export_heading_font)
        export_layout.addWidget(export_heading)
        export_note = QLabel('Select the current display-server view details to include in the export.')
        export_note.setWordWrap(True)
        export_layout.addWidget(export_note)

        self.export_columns = []
        for column in owner.columns:
            checkbox = QCheckBox(column[1])
            checkbox.setChecked(True)
            export_layout.addWidget(checkbox)
            self.export_columns.append((checkbox, column))
        self.export_source = QCheckBox('Acquisition Source')
        self.export_source.setChecked(True)
        export_layout.addWidget(self.export_source)
        self.export_metadata = QCheckBox('Metadata Details')
        self.export_metadata.setChecked(False)
        export_layout.addWidget(self.export_metadata)

        export_layout.addStretch(1)
        export_row = QHBoxLayout()
        export_row.addStretch(1)
        export_button = QPushButton('Export...')
        export_button.clicked.connect(self._export_selected)
        export_row.addWidget(export_button)
        export_layout.addLayout(export_row)
        tabs.addTab(export_page, 'Export')

        # About — exact Kernel Modules structure/branding conventions.
        about_page = QWidget()
        about_layout = QVBoxLayout(about_page)
        about_layout.setContentsMargins(24, 20, 24, 18)
        about_layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(112, 112)
        icon_path = Path(__file__).resolve().parent / 'icon.png'
        if icon_path.is_file():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                icon_label.setPixmap(
                    pixmap.scaled(
                        112, 112,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        about_layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        name = QLabel("<h2 style='margin:0'>Display Server</h2>")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(name)
        version = QLabel(f'Version {APPLET_VERSION}')
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(version)
        slogan = QLabel('<b>Expose. Explore. Explain.</b>')
        slogan.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(slogan)
        description = QLabel(
            'A read-only LinSpectacles applet for inspecting the current graphical '
            'session, compositor, display outputs, modes and reported protocols.'
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(description)
        details = QLabel(
            '<b>Build:</b> Standalone LinSpectacles applet<br>'
            '<b>Organisation ID:</b> '
            "<a href='https://github.com/linspectacles/'>linspectacles</a><br>"
            f'<b>Applet ID:</b> {APPLET_ID}'
        )
        details.setWordWrap(True)
        details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details.setOpenExternalLinks(True)
        details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(details)
        copyright_label = QLabel(
            'Copyright © 2026 '
            "<a href='https://github.com/brunonlinespace'>brunonlinespace</a>"
        )
        copyright_label.setOpenExternalLinks(True)
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(copyright_label)
        license_label = QLabel('Licensed under GNU GPLv3 or later.')
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(license_label)
        readme_url = QUrl.fromLocalFile(
            str(Path(__file__).resolve().parent.parent / 'README.md')
        ).toString()
        license_url = QUrl.fromLocalFile(
            str(Path(__file__).resolve().parent.parent / 'LICENSE')
        ).toString()
        links = QLabel(
            f"<a href='{readme_url}'>README</a>"
            '&nbsp;·&nbsp; '
            f"<a href='{license_url}'>License</a>"
            '&nbsp;·&nbsp; '
            f"<a href='{REPOSITORY_URL}'>Repository</a>"
        )
        links.setOpenExternalLinks(True)
        links.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(links)
        about_layout.addStretch(1)
        tabs.addTab(about_page, 'About')

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _layout_changed(self, text):
        self.owner.set_details_orientation(str(text).strip().lower(), persist=True)

    def _metadata_panel_changed(self, visible):
        self.owner.set_metadata_panel_visible(bool(visible), persist=True)

    def _export_selected(self):
        selected = [column for checkbox, column in self.export_columns if checkbox.isChecked()]
        include_metadata = self.export_metadata.isChecked()
        if self.export_source.isChecked():
            selected.append(('source', 'Acquisition Source', 180, 'left'))
        if include_metadata:
            selected.append(('metadata_details', 'Metadata Details', 520, 'left'))
        if not selected:
            QMessageBox.information(self, 'Export', 'Select at least one detail to export.')
            return
        keys = {column[0] for column in selected}
        records = []
        for raw in self.owner.get_export_records():
            record = {key: raw.get(key, '') for key in keys if key != 'metadata_details'}
            if include_metadata:
                record['metadata_details'] = self.owner.metadata_details_for_export(raw)
            records.append(record)
        if not records:
            QMessageBox.information(self, 'Export', 'There is no collected data to export yet.')
            return
        path = export_records_dialog(self, APPLET_NAME, records, columns=selected)
        if path is not None:
            self.owner.set_status(f'Exported data to {path}')


# Keep a running, unparented QThread alive even if its applet is closed. Qt
# disconnects the destroyed receiver; the thread exits after bounded probes.
_ACTIVE_WORKERS = set()


def _join_active_workers():
    """Do not destroy running QThreads during application shutdown."""
    for worker in list(_ACTIVE_WORKERS):
        if worker.isRunning():
            worker.wait()  # All probes have finite timeouts; no persistent capture.


class _SnapshotWorker(QThread):
    snapshot_ready = pyqtSignal(object, object)

    def run(self):
        try:
            self.snapshot_ready.emit(collect_snapshot(), None)
        except Exception as exc:
            self.snapshot_ready.emit(None, f'{type(exc).__name__}: {exc}')



class DisplayServerTab(BaseInspectorTab):
    NUMERIC_COLUMNS = {'pid', 'version', 'refresh', 'scale'}

    def __init__(self, parent=None):
        self.settings = QSettings('brunonlinespace', SETTINGS_NAME)
        self.snapshot = None
        self.acquired = False
        self._view_name = VIEWS[0]
        self._host_column_callback = None
        self._host_settings = {}
        self._sort_state = {}
        self._changing_view = False
        self._initial_refresh_pending = False
        self._first_refresh_attempted = False
        self._worker = None
        self._initializing_view = True
        super().__init__('Total Session Records', _view_columns(self._view_name), list(VIEWS), parent)
        self.export_title = APPLET_NAME

        # Exactly the authoritative compact top row, without extra headings.
        self.export_btn.setText('Options...')
        try:
            self.export_btn.clicked.disconnect()
        except TypeError:
            pass
        self.export_btn.clicked.connect(self.show_options)
        self.export_btn.setEnabled(True)

        self.category_label.setText('View:')
        self.category_dropdown.setMinimumWidth(190)
        # Keep the same Kernel Modules widgets, but put View on the top-right
        # action row immediately before Refresh List and Options.
        self._place_view_selector_in_action_row()
        self.search_entry.setPlaceholderText('Search items...')

        self.details_orientation = 'horizontal'
        self._load_details_orientation()
        self.metadata_panel_visible = True
        self._load_metadata_panel_visibility()

        self._shortcuts = []
        self._install_shortcuts()
        self.table.horizontalHeader().sectionResized.connect(self._column_resized)
        self._restore_view_choice()
        self._changing_view = True
        try:
            # Even the default Session view must restore its saved schema.
            self.column_visibility.set_changed_callback(self._columns_changed)
            self._view_column_state()
        finally:
            self._changing_view = False
            self._initializing_view = False
        self.set_status('Ready - Current graphical session will be acquired on opening.')

    def _place_view_selector_in_action_row(self):
        """Move the inherited category widgets; retain their signal wiring."""
        filter_layout = self.layout().itemAt(1).layout()
        filter_layout.removeWidget(self.category_label)
        filter_layout.removeWidget(self.category_dropdown)
        refresh_index = self.dash_layout.indexOf(self.refresh_btn)
        self.dash_layout.insertWidget(refresh_index, self.category_label)
        self.dash_layout.insertWidget(refresh_index + 1, self.category_dropdown)

    def showEvent(self, event):
        """Acquire once when the applet is shown, not when merely constructed."""
        super().showEvent(event)
        if not self._first_refresh_attempted and not self._initial_refresh_pending:
            self._initial_refresh_pending = True
            QTimer.singleShot(0, self._refresh_when_shown)

    def _refresh_when_shown(self):
        self._initial_refresh_pending = False
        if self.isVisible() and not self._first_refresh_attempted:
            self.load_modules()

    def _restore_view_choice(self):
        view = str(self.settings.value('view', VIEWS[0]) or VIEWS[0])
        if view in VIEWS:
            self.category_dropdown.setCurrentText(view)

    def _view_column_state(self):
        """Restore width and visibility for the active view, matching support policy."""
        header = self.table.horizontalHeader()
        for index, (key, _label, width, _align) in enumerate(self.columns):
            try:
                saved = int(self.settings.value(f'columns/{self._view_name}/{key}', width))
            except (TypeError, ValueError):
                saved = width
            self.table.setColumnWidth(index, max(65, min(saved, 700)))
        hidden = self.settings.value(f'hidden/{self._view_name}', [])
        if isinstance(hidden, str):
            hidden = [hidden] if hidden else []
        if not isinstance(hidden, (list, tuple)):
            hidden = []
        self.column_visibility.apply_hidden(hidden)

    def _column_resized(self, index, _old, new):
        if self._changing_view or not (0 <= index < len(self.columns)):
            return
        key = self.columns[index][0]
        self.settings.setValue(f'columns/{self._view_name}/{key}', new)

    def _save_current_widths(self):
        for index, (key, _label, _width, _align) in enumerate(self.columns):
            if not self.table.isColumnHidden(index):
                self.settings.setValue(
                    f'columns/{self._view_name}/{key}', self.table.columnWidth(index)
                )

    def _columns_changed(self, hidden):
        self.settings.setValue(f'hidden/{self._view_name}', hidden)
        if callable(self._host_column_callback):
            self._host_column_callback(hidden)

    def _switch_view(self, view):
        if not self._initializing_view:
            self._save_current_widths()
        self._changing_view = True
        self._view_name = view
        self.settings.setValue('view', view)
        self.columns = _view_columns(view)
        self.total_label_text = f'Total {view} Records'
        self.table.blockSignals(True)
        try:
            self.table.setSortingEnabled(False)
            self.table.clear()
            self.table.setColumnCount(len(self.columns))
            self.table.setHorizontalHeaderLabels([column[1] for column in self.columns])
            self.table.setRowCount(0)
            # Reconfigure the same authoritative controller for each view schema.
            header = self.table.horizontalHeader()
            try:
                header.customContextMenuRequested.disconnect()
            except TypeError:
                pass
            self.column_visibility = ColumnVisibilityController(
                self.table, self.columns, self.set_status
            )
            self.column_visibility.set_changed_callback(self._columns_changed)
            self._view_column_state()
        finally:
            self.table.blockSignals(False)
            self._changing_view = False

    def _current_view_records(self):
        if not self.snapshot:
            return []
        return list(self.snapshot['data'].get(self._view_name, []))

    def _flatten_records(self):
        rows = []
        for record in self._current_view_records():
            flat = dict(record['columns'])
            flat['category'] = self._view_name
            flat['_record'] = record
            rows.append(flat)
        return rows

    def filter_modules(self, *_):
        view = self.category_dropdown.currentText()
        if not view or view not in VIEWS:
            return
        view_changed = view != self._view_name
        if view_changed:
            self._switch_view(view)
        self.modules_data = self._flatten_records()
        key, reverse = self._sort_state.get(view, (self.columns[0][0], False))
        self.modules_data.sort(key=lambda row: inventory_sort_key(key, row.get(key, '')),
                               reverse=reverse)
        self.stats_label.setText(f'{self.total_label_text}: {len(self.modules_data)}')
        # Inherited filter owns table rendering, empty details, and selection sync.
        super().filter_modules()
        self.export_btn.setEnabled(True)  # Options remain available before acquisition.
        if not self.search_entry.text().strip():
            self.filter_status_lbl.clear()
        self._show_empty_explanation()
        if view_changed and self.snapshot and self._current_view_records():
            self.set_status(f'{view}: {len(self._current_view_records())} reported records '
                            f"(acquired {self.snapshot['acquired']}).")

    def _show_empty_explanation(self):
        # No extra permanent control: use the existing Metadata Details and
        # status surfaces when the authoritative inventory has no records.
        if not self.snapshot or self._current_view_records():
            return
        reason = self.snapshot.get('empty_reasons', {}).get(
            self._view_name, 'No records were reported by available sources')
        self.clear_info()
        self.append_info(f'--- {self._view_name} ---\n\n{reason}\n')
        notes = self.snapshot.get('diagnostics', [])
        if notes:
            self.append_info('\n--- Acquisition Notes ---\n')
            for note in notes:
                self.append_info(str(note) + '\n')
        self.set_status(f'{self._view_name}: {reason}')

    def sort_by(self, column_id):
        previous = self._sort_state.get(self._view_name)
        reverse = previous is not None and previous[0] == column_id and not previous[1]
        self._sort_state[self._view_name] = (column_id, reverse)
        self.filter_modules()

    def load_modules(self):
        """Collect on demand using one bounded worker, never blocking Qt."""
        self._first_refresh_attempted = True
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.set_status('Acquiring graphical session snapshot...')
        app = QApplication.instance()
        if app is not None and not getattr(app, '_display_server_shutdown_hook', False):
            app.aboutToQuit.connect(_join_active_workers)
            app._display_server_shutdown_hook = True
        worker = _SnapshotWorker()
        self._worker = worker
        _ACTIVE_WORKERS.add(worker)
        worker.snapshot_ready.connect(self._accept_snapshot)
        worker.finished.connect(lambda w=worker: _ACTIVE_WORKERS.discard(w))
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._refresh_finished)
        worker.start()

    def _accept_snapshot(self, snapshot, error):
        if error or snapshot is None:
            self.snapshot = None
            self.acquired = False
            self.filter_modules()
            self.set_status('Acquisition failed: ' + (error or 'Unknown collector error'))
            return
        self.snapshot = snapshot
        self.acquired = True
        self.filter_modules()
        count = sum(len(records) for records in snapshot['data'].values())
        if self._current_view_records():
            self.set_status(
                f"Acquired {snapshot['acquired']} — {snapshot['session_type']} session; "
                f'{count} reported records across five views.'
            )

    def _refresh_finished(self):
        self._worker = None
        self.refresh_btn.setEnabled(True)


    def on_module_select(self):
        record = self.current_record()
        if not record:
            self.clear_info()
            return
        self._render_record_details(record)

    def _render_record_details(self, record):
        raw = record.get('_record', {})
        self.clear_info()
        if not raw:
            return
        self.append_info(f'--- {self._view_name} ---\n')
        for key, value in raw.get('columns', {}).items():
            self.append_key_value(key.replace('_', ' ').title(), _flat(value))
        self.append_info('\n--- Source & Details ---\n')
        for key, value in raw.get('detail', {}).items():
            self.append_key_value(key, _flat(value))
        self.info_text.moveCursor(QTextCursor.MoveOperation.Start)
        self.info_text.verticalScrollBar().setValue(0)

    def metadata_details_for_export(self, record):
        # Do not change selection or visible panel merely to export metadata.
        raw = record.get('_record', {})
        if not raw:
            return ''
        lines = [f'--- {self._view_name} ---']
        for key, value in raw.get('columns', {}).items():
            lines.append(f"{key.replace('_', ' ').title()}: {_flat(value)}")
        lines.append('')
        lines.append('--- Source & Details ---')
        for key, value in raw.get('detail', {}).items():
            lines.append(f'{key}: {_flat(value)}')
        return '\n'.join(lines) + '\n'

    def get_export_records(self):
        result = []
        for row in self.modules_data:
            selected = {column_id: _flat(row.get(column_id, '')) for column_id, *_ in self.columns}
            selected['source'] = _flat(row.get('_record', {}).get('source', 'Not exposed'))
            selected['_record'] = row.get('_record', {})
            result.append(selected)
        return result

    def sources_text(self):
        lines = [
            'Display Server is read-only. Its displayed facts come from these interfaces.',
            '',
            'Graphical session identity and environment',
            '  XDG_SESSION_TYPE, XDG_SESSION_ID, XDG_CURRENT_DESKTOP, WAYLAND_DISPLAY, DISPLAY',
            '  XDG_RUNTIME_DIR; optional loginctl show-session (ID, self, validated auto)', 
            '',
            'Display stack and endpoint evidence',
            '  Session Wayland/X11 endpoints; corroborated /proc session/socket ownership',
            '  /proc/net/unix and /proc/<pid>/fd socket inodes; optional component versions',
            '',
            'Wayland registry and basic output advertisement',
            '  wayland-info',
            '',
            'GNOME / Mutter current monitor state (when accessible)',
            '  org.gnome.Mutter.DisplayConfig.GetCurrentState via optional python3-gobject',
            '',
            'KDE / KScreen output information (when accessible)',
            '  kscreen-doctor -j',
            '',
            'wlroots output-management (where available)',
            '  wlr-randr --json',
            '',
            'Native X11 output modes and extensions',
            '  xrandr --query; xdpyinfo (native X11 only)', 
            '',
            'Important distinctions',
            '  Wayland with XWayland is still a Wayland session.',
            '  XWayland RandR cannot establish real physical output properties.',
            '  Advertised protocols do not prove feature enablement.',
            '  Unreported data is not automatically unsupported.',
            '  No privileged helpers or compositor-setting changes are performed.',
        ]
        if self.snapshot:
            lines += [
                '',
                'Last acquisition',
                f"  {self.snapshot['acquired']}",
                '',
                'Reported session type',
                f"  {self.snapshot['session_type']}",
            ]
            if self.snapshot.get('diagnostics'):
                lines += ['', 'Acquisition notes']
                lines.extend('  ' + _flat(item) for item in self.snapshot['diagnostics'])
        else:
            lines += ['', 'Acquisition', '  Not acquired yet; automatic acquisition begins on first display.']
        return '\n'.join(lines)

    def show_options(self):
        DisplayServerOptionsDialog(self).exec()

    def _add_shortcut(self, sequence, callback):
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)
        return shortcut

    def _install_shortcuts(self):
        self._add_shortcut('F3', self.toggle_metadata_panel)
        self._add_shortcut('Ctrl+L', self.toggle_details_orientation)
        self._add_shortcut('Ctrl+/', self.show_options)
        self._add_shortcut('Shift+F5', self.load_modules)
        for index in range(len(VIEWS)):
            self._add_shortcut(
                f'Ctrl+{index + 1}',
                lambda i=index: self.category_dropdown.setCurrentIndex(i),
            )

    def toggle_details_orientation(self):
        target = 'vertical' if self.details_orientation == 'horizontal' else 'horizontal'
        self.set_details_orientation(target, persist=True)

    def _load_metadata_panel_visibility(self):
        settings = QSettings('brunonlinespace', SETTINGS_NAME)
        value = settings.value('metadata_panel_visible', True)
        if isinstance(value, str):
            visible = value.strip().lower() not in {'0', 'false', 'no', 'off'}
        else:
            visible = bool(value)
        self.set_metadata_panel_visible(visible, persist=False)

    def set_metadata_panel_visible(self, visible, *, persist=True):
        self.metadata_panel_visible = bool(visible)
        details_panel = self.splitter.widget(1)
        if details_panel is not None:
            details_panel.setVisible(self.metadata_panel_visible)
        if self.metadata_panel_visible:
            self.set_details_orientation(self.details_orientation, persist=False)
        if persist:
            settings = QSettings('brunonlinespace', SETTINGS_NAME)
            settings.setValue('metadata_panel_visible', self.metadata_panel_visible)
            settings.sync()

    def toggle_metadata_panel(self):
        self.set_metadata_panel_visible(not self.metadata_panel_visible, persist=True)

    def _load_details_orientation(self):
        settings = QSettings('brunonlinespace', SETTINGS_NAME)
        orientation = str(settings.value('details_orientation', 'horizontal') or 'horizontal').lower()
        if orientation not in {'horizontal', 'vertical'}:
            orientation = 'horizontal'
        self.set_details_orientation(orientation, persist=False)

    def set_details_orientation(self, orientation, *, persist=True):
        orientation = str(orientation or 'horizontal').lower()
        if orientation not in {'horizontal', 'vertical'}:
            orientation = 'horizontal'
        self.details_orientation = orientation
        details_panel = self.splitter.widget(1)
        details_layout = details_panel.layout() if details_panel is not None else None
        if orientation == 'vertical':
            self.splitter.setOrientation(Qt.Orientation.Vertical)
            if details_layout is not None:
                details_layout.setContentsMargins(0, 8, 0, 0)
            self.splitter.setSizes([430, 330])
        else:
            self.splitter.setOrientation(Qt.Orientation.Horizontal)
            if details_layout is not None:
                details_layout.setContentsMargins(8, 0, 0, 0)
            self.splitter.setSizes([480, 700])
        if persist:
            settings = QSettings('brunonlinespace', SETTINGS_NAME)
            settings.setValue('details_orientation', orientation)
            settings.sync()

    def apply_host_settings(self, settings=None, column_visibility_callback=None):
        self._host_settings = dict(settings or {})
        self._host_column_callback = column_visibility_callback
        super().apply_host_settings(settings, None)
        # Host font applies to the same QTextEdit + QTextDocument used by KM.
        self.column_visibility.set_changed_callback(self._columns_changed)


def create_applet(parent=None):
    return DisplayServerTab(parent=parent)


def run_standalone():
    import sys
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from ._support import STANDALONE_STYLESHEET
    app = QApplication(sys.argv)
    app.setApplicationName(APPLET_NAME)
    app.setOrganizationName(APPLET_AUTHOR)
    icon_path = Path(__file__).resolve().parent / 'icon.png'
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(STANDALONE_STYLESHEET)
    window = QMainWindow()
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.setWindowTitle(f'{APPLET_NAME} {APPLET_VERSION} — LinSpectacles Applet')
    window.resize(1200, 780)
    window.setCentralWidget(create_applet())
    window.show()
    return app.exec()
