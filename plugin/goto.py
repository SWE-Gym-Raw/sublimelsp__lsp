from __future__ import annotations
from .core.promise import Promise
from .core.protocol import Location
from .core.protocol import LocationLink
from .core.protocol import Request
from .core.registry import get_position
from .core.registry import LspTextCommand
from .core.sessions import Session, method_to_capability
from .core.views import get_symbol_kind_from_scope
from .core.views import text_document_position_params
from .locationpicker import LocationPicker
from .locationpicker import open_location_async
from functools import partial
from typing_extensions import List, TypeAlias, Union
import sublime

GotoResponse: TypeAlias = Union[None, Location, List[Location], List[LocationLink]]


class LspGotoCommand(LspTextCommand):

    method = ''
    placeholder_text = ''
    fallback_command = ''

    def is_enabled(
        self,
        event: dict | None = None,
        point: int | None = None,
        side_by_side: bool = False,
        force_group: bool = True,
        fallback: bool = False,
        group: int = -1
    ) -> bool:
        return fallback or super().is_enabled(event, point)

    def is_visible(
        self,
        event: dict | None = None,
        point: int | None = None,
        side_by_side: bool = False,
        force_group: bool = True,
        fallback: bool = False,
        group: int = -1
    ) -> bool:
        if self.applies_to_context_menu(event):
            return self.is_enabled(event, point, side_by_side, force_group, fallback, group)
        return True

    def run(
        self,
        _: sublime.Edit,
        event: dict | None = None,
        point: int | None = None,
        side_by_side: bool = False,
        force_group: bool = True,
        fallback: bool = False,
        group: int = -1
    ) -> None:
        sessions = list(self.sessions(self.capability))
        position = get_position(self.view, event, point)
        if sessions and position is not None:
            requests: list[Promise[GotoResponse]] = []
            params = text_document_position_params(self.view, position)
            last_session = sessions[0]
            for session in sessions:
                request = Request(self.method, params, self.view, progress=True)
                requests.append(session.send_request_task(request))
            Promise.all(requests).then(
                partial(self._handle_responses_async, last_session, side_by_side, force_group, fallback, group, position))
        else:
            self._handle_no_results(fallback, side_by_side)

    def _handle_responses_async(
        self,
        session: Session,
        side_by_side: bool,
        force_group: bool,
        fallback: bool,
        group: int,
        position: int,
        responses: list[GotoResponse]
    ) -> None:
        print(responses)
        # Normalize all responses to LocationLink.
        results: list[LocationLink] = []
        for response in responses:
            if not response:
                continue
            if not isinstance(response, list):
                response = [response]
            for location in response:
                if 'targetUri' in location:
                    results.append(location)
                else:
                    # Convert Location to LocationLink.
                    results.append({
                        "targetUri": location["uri"],
                        "targetRange": location["range"],
                        "targetSelectionRange": location["range"]
                    })
        self._handle_response_async(session, side_by_side, force_group, fallback, group, position, results)

    def _handle_response_async(
        self,
        session: Session,
        side_by_side: bool,
        force_group: bool,
        fallback: bool,
        group: int,
        position: int,
        response: GotoResponse
    ) -> None:
        if isinstance(response, dict):
            self.view.run_command("add_jump_record", {"selection": [(r.a, r.b) for r in self.view.sel()]})
            open_location_async(session, response, side_by_side, force_group, group)
        elif isinstance(response, list):
            if len(response) == 0:
                self._handle_no_results(fallback, side_by_side)
            elif len(response) == 1:
                self.view.run_command("add_jump_record", {"selection": [(r.a, r.b) for r in self.view.sel()]})
                open_location_async(session, response[0], side_by_side, force_group, group)
            else:
                self.view.run_command("add_jump_record", {"selection": [(r.a, r.b) for r in self.view.sel()]})
                placeholder = self.placeholder_text + " " + self.view.substr(self.view.word(position))
                kind = get_symbol_kind_from_scope(self.view.scope_name(position))
                sublime.set_timeout(
                    partial(LocationPicker,
                            self.view, session, response, side_by_side, force_group, group, placeholder, kind)
                )
        else:
            self._handle_no_results(fallback, side_by_side)

    def _handle_no_results(self, fallback: bool = False, side_by_side: bool = False) -> None:
        window = self.view.window()

        if not window:
            return

        if fallback and self.fallback_command:
            window.run_command(self.fallback_command, {"side_by_side": side_by_side})
        else:
            window.status_message("No results found")


class LspSymbolDefinitionCommand(LspGotoCommand):
    method = "textDocument/definition"
    capability = method_to_capability(method)[0]
    placeholder_text = "Definitions of"
    fallback_command = "goto_definition"


class LspSymbolTypeDefinitionCommand(LspGotoCommand):
    method = "textDocument/typeDefinition"
    capability = method_to_capability(method)[0]
    placeholder_text = "Type Definitions of"


class LspSymbolDeclarationCommand(LspGotoCommand):
    method = "textDocument/declaration"
    capability = method_to_capability(method)[0]
    placeholder_text = "Declarations of"


class LspSymbolImplementationCommand(LspGotoCommand):
    method = "textDocument/implementation"
    capability = method_to_capability(method)[0]
    placeholder_text = "Implementations of"
