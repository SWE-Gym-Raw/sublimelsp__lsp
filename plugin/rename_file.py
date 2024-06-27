from __future__ import annotations
from .core.open import open_file_uri
from .core.protocol import Notification, RenameFilesParams, Request, WorkspaceEdit
from .core.registry import LspWindowCommand
from pathlib import Path
from urllib.parse import urljoin
import os
import sublime
import sublime_plugin


class RenameFileInputHandler(sublime_plugin.TextInputHandler):
    def want_event(self) -> bool:
        return False

    def __init__(self, path: str) -> None:
        self.path = path

    def name(self) -> str:
        return "new_name"

    def placeholder(self) -> str:
        return self.path

    def initial_text(self) -> str:
        return self.placeholder()

    def initial_selection(self) -> list[tuple[int, int]]:
        end_point = self.path.rfind('.')
        if end_point == -1:
            end_point = len(self.path)
        return [(0, end_point)]

    def validate(self, path: str) -> bool:
        return len(path) > 0


class LspRenameFileCommand(LspWindowCommand):
    capability = 'workspace.fileOperations.willRename'

    def is_enabled(self):
        return True

    def is_visible(self, dirs=None, files=None):
        if dirs is None and files is None:
            return True  # show 'LSP: Rename File' in command palette
        if dirs is not None:
            return len(dirs) == 1  # show 'LSP: Rename Folder' in sidebar
        if files is not None:
            return len(files) == 1  # show 'LSP: Rename File' in sidebar
        return False

    def want_event(self) -> bool:
        return False

    def input(self, args: dict) -> sublime_plugin.TextInputHandler | None:
        if "new_name" in args:
            return None
        old_path = self.get_old_path(args.get('dirs'), args.get('files'), self.window.active_view())
        return RenameFileInputHandler(Path(old_path).name)

    def run(
        self,
        new_name: str,  # new_name can be: FILE_NAME.xy OR ./FILE_NAME.xy OR ../../FILE_NAME.xy
        dirs: list[str] | None = None,  # exist when invoked from the sidebar with "LSP: Rename Folder"
        files: list[str] | None = None,  # exist when invoked from the sidebar with "LSP: Rename File"
    ) -> None:
        session = self.session()
        view = self.window.active_view()
        old_path = self.get_old_path(dirs, files, view)
        new_path = os.path.normpath(Path(old_path).parent / new_name)
        if os.path.exists(new_path):
            self.window.status_message('Unable to Rename. Already exists')
            return
        if old_path == '' and view:  # handle renaming buffers
            view.set_name(Path(new_path).name)
            return
        rename_file_params: RenameFilesParams = {
            "files": [{
                "newUri": urljoin("file:", new_path),
                "oldUri": urljoin("file:", old_path),
            }]
        }
        if not session:
            self.rename_path(old_path, new_path)
            self.notify_did_rename(rename_file_params)
            return
        request = Request.willRenameFiles(rename_file_params)
        session.send_request(
            request,
            lambda res: self.handle(res, session.config.name, old_path, new_path, rename_file_params)
        )

    def get_old_path(self, dirs: list[str] | None, files: list[str] | None, view: sublime.View | None) -> str:
        if dirs:
            return dirs[0]
        if files:
            return files[0]
        if view:
            return view.file_name() or ""
        return ""

    def handle(self, res: WorkspaceEdit | None, session_name: str,
               old_path: str, new_path: str, rename_file_params: RenameFilesParams) -> None:
        session = self.session_by_name(session_name)
        if session:
            # LSP spec - Apply WorkspaceEdit before the files are renamed
            if res:
                session.apply_workspace_edit_async(res, is_refactoring=True)
            self.rename_path(old_path, new_path)
            self.notify_did_rename(rename_file_params)

    def rename_path(self, old_path: str, new_path: str) -> None:
        old_regions: list[sublime.Region] = []
        view = self.window.find_open_file(old_path)
        if view:
            old_regions = [region for region in view.sel()]
            view.close()  # LSP spec - send didClose for the old file
        new_dir = Path(new_path).parent
        if not os.path.exists(new_dir):
            os.makedirs(new_dir)
        os.rename(old_path, new_path)
        if os.path.isfile(new_path):
            def restore_regions(v: sublime.View | None) -> None:
                if not v:
                    return
                v.sel().clear()
                v.sel().add_all(old_regions)

            # LSP spec - send didOpen for the new file
            open_file_uri(self.window, new_path).then(restore_regions)

    def notify_did_rename(self, rename_file_params: RenameFilesParams):
        sessions = [s for s in self.sessions() if s.has_capability('workspace.fileOperations.didRename')]
        for s in sessions:
            s.send_notification(Notification.didRenameFiles(rename_file_params))
