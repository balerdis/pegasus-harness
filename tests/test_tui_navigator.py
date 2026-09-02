"""Navigation as pure logic: what is on screen, and what a key does next.

Every scenario here presses keys and checks where a person ends up. None of
it touches a terminal, because :class:`Navigator` never touches one either.
"""
from __future__ import annotations

import unittest

import pegasus
from pegasus.tui import navigator as navigator_module
from pegasus.tui.navigator import (
    CANCEL,
    Action,
    AgentRow,
    CliOption,
    Entry,
    InstallPlanScreen,
    InstallResultScreen,
    InstallTarget,
    McpOption,
    McpSelectionScreen,
    Menu,
    ModelOption,
    ModelsScreen,
    ModelsTarget,
    Navigator,
    Placeholder,
    ProviderOption,
    RestoreConfirm,
    RestoreResultScreen,
    RestoreTarget,
    STARTUP_MESSAGE,
    StatusRequest,
    StatusScreen,
    BehindInstall,
    UninstallConfirm,
    UninstallResultScreen,
    UninstallTarget,
    UpdateNotice,
    UpdateTarget,
    UpgradeTarget,
    PEGASUS_PROGRAM,
    REMOTE_UPDATE_REMEDY,
    busy_message_for,
    install_menu,
    main_menu,
    models_menu,
    restore_menu,
    uninstall_menu,
    update_menu,
    update_notice_lines,
)

SAMPLE = CliOption(id="demo", display_name="Demo CLI", config_dir="/home/x/.demo", tier="full")

REASONING_MODEL = ModelOption(id="deep-thinker", reasoning=True)
PLAIN_MODEL = ModelOption(id="fast-model", reasoning=False)
PROVIDERS = (
    ProviderOption(id="anthropic", models=(REASONING_MODEL,)),
    ProviderOption(id="openai", models=(PLAIN_MODEL,)),
)
ROWS = (AgentRow(agent="sdd-apply", current=None), AgentRow(agent="sdd-verify", current="anthropic/claude-sonnet-5"))


def _models_screen(**overrides) -> ModelsScreen:
    fields = {"cli": SAMPLE, "providers": PROVIDERS, "rows": ROWS}
    fields.update(overrides)
    return ModelsScreen(**fields)


class MainMenuTest(unittest.TestCase):
    def test_the_session_starts_on_the_main_menu(self):
        navigator = Navigator.starting()
        self.assertIsInstance(navigator.current, Menu)

    def test_the_main_menu_has_the_documented_entries_in_order(self):
        # Grouped by intent: get working and keep current (Install, Update,
        # Upgrade), then configure, then inspect, then remove -- Uninstall
        # last before Exit so arrow-key navigation is less likely to land on
        # the destructive entry by accident.
        navigator = Navigator.starting()
        labels = [entry.label for entry in navigator.current.entries]
        self.assertEqual(
            labels,
            ["Install", "Update", "Upgrade", "Configure models", "Status and diagnostics", "Uninstall", "Exit"],
        )

    def test_the_title_names_the_running_release(self):
        navigator = Navigator.starting()
        self.assertEqual(navigator.current.title, f"Pegasus Harness {pegasus.__version__}")

    def test_the_cursor_starts_on_the_first_entry(self):
        navigator = Navigator.starting()
        self.assertEqual(navigator.cursor, 0)


class MovementTest(unittest.TestCase):
    def test_moving_down_advances_the_cursor(self):
        navigator = Navigator.starting().handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.cursor, 1)

    def test_moving_up_from_the_first_entry_wraps_to_the_last(self):
        navigator = Navigator.starting().handle(Action.MOVE_UP)
        self.assertEqual(navigator.cursor, len(navigator.current.entries) - 1)

    def test_moving_down_from_the_last_entry_wraps_to_the_first(self):
        navigator = Navigator.starting()
        for _ in range(len(navigator.current.entries) - 1):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.cursor, 0)

    def test_moving_never_changes_which_screen_is_current(self):
        navigator = Navigator.starting()
        before = navigator.current
        navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertIs(navigator.current, before)


class ToggleIsInertElsewhereTest(unittest.TestCase):
    """Space only means something on the mcp selection screen's server rows
    -- every other screen must treat `Action.TOGGLE` as a no-op, the same
    inert reading a stray key gets everywhere `handle` falls through to
    `return self`."""

    def test_toggle_does_nothing_on_the_main_menu(self):
        navigator = Navigator.starting()
        before = navigator
        navigator = navigator.handle(Action.TOGGLE)
        self.assertEqual(navigator, before)

    def test_toggle_does_nothing_on_a_result_screen(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE).opened(
            InstallResultScreen(cli=SAMPLE, report={"status": "installed"})
        )
        before = navigator
        navigator = navigator.handle(Action.TOGGLE)
        self.assertEqual(navigator, before)


class EnteringAndLeavingAScreenTest(unittest.TestCase):
    def test_choosing_an_entry_enters_the_screen_it_names(self):
        expected = Navigator.starting().current.entries[0].target
        navigator = Navigator.starting().handle(Action.CHOOSE)
        self.assertEqual(navigator.current, expected)

    def test_a_screen_not_built_yet_is_a_placeholder_that_says_so(self):
        navigator = Navigator.starting().handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertTrue(navigator.current.note)

    def test_going_back_returns_to_the_main_menu(self):
        navigator = Navigator.starting().handle(Action.CHOOSE)
        navigator = navigator.handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)

    def test_going_back_restores_the_cursor_that_was_left_on_the_menu(self):
        navigator = Navigator.starting()
        navigator = navigator.handle(Action.MOVE_DOWN).handle(Action.MOVE_DOWN)
        remembered = navigator.cursor
        navigator = navigator.handle(Action.CHOOSE).handle(Action.BACK)
        self.assertEqual(navigator.cursor, remembered)

    def test_choosing_a_placeholder_screen_also_returns_to_the_menu(self):
        """Nothing to configure there yet, so acknowledging it is the same as leaving it."""
        navigator = Navigator.starting().handle(Action.CHOOSE)
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)

    def test_going_back_at_the_root_menu_stays_put(self):
        navigator = Navigator.starting()
        after = navigator.handle(Action.BACK)
        self.assertEqual(after, navigator)


class QuittingTest(unittest.TestCase):
    def test_the_session_does_not_start_quit(self):
        self.assertFalse(Navigator.starting().quit)

    def test_choosing_exit_quits(self):
        navigator = Navigator.starting()
        exit_index = [entry.label for entry in navigator.current.entries].index("Exit")
        for _ in range(exit_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)
        self.assertTrue(navigator.quit)

    def test_the_quit_action_works_from_a_nested_screen_too(self):
        navigator = Navigator.starting().handle(Action.CHOOSE).handle(Action.QUIT)
        self.assertTrue(navigator.quit)

    def test_a_quit_session_ignores_further_keys(self):
        quit_navigator = Navigator.starting().handle(Action.QUIT)
        self.assertEqual(quit_navigator.handle(Action.MOVE_DOWN), quit_navigator)


class InstallMenuTest(unittest.TestCase):
    """The `¿Dónde instalar Pegasus?` screen: built from whichever CLIs were
    detected present, with nothing here doing any of that detecting."""

    def test_a_detected_cli_opens_a_menu_naming_it(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current.entries[0].target, InstallTarget(SAMPLE))

    def test_the_entry_names_the_install_command(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE)
        self.assertEqual(navigator.current.entries[0].target.command, "install")

    def test_no_detected_cli_still_shows_a_placeholder_that_says_why(self):
        navigator = Navigator.starting(detections=()).handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertIn("No supported CLI", navigator.current.note)

    def test_going_back_from_the_cli_choice_returns_to_the_main_menu(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE).handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current, Navigator.starting(detections=(SAMPLE,)).current)

    def test_choosing_a_cli_directly_does_nothing_by_itself(self):
        """Fetching a plan is real engine work only `session` can do; asking
        `Navigator` alone for it must never invent a screen to stand in for
        the report it cannot fetch."""
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class InstallPlanAndResultScreensTest(unittest.TestCase):
    """Once `session` has fetched a report, `Navigator` treats the screen it
    becomes like any other leaf: an acknowledgement returns to whatever
    opened it."""

    def plan(self) -> Navigator:
        return Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE).opened(
            InstallPlanScreen(cli=SAMPLE, report={"status": "planned"})
        )

    def result(self) -> Navigator:
        return self.plan().opened(InstallResultScreen(cli=SAMPLE, report={"status": "installed"}))

    def test_backing_out_of_a_plan_returns_to_the_cli_choice(self):
        navigator = self.plan().handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current.entries[0].target, InstallTarget(SAMPLE))

    def test_acknowledging_a_result_leaves_it(self):
        navigator = self.result().handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)


MCP_OPTIONS = (
    McpOption(id="cbm", description="Knowledge graph of the codebase"),
    McpOption(id="context7", description="Up-to-date third-party docs"),
)


def _mcp_screen(**overrides) -> McpSelectionScreen:
    fields = {"cli": SAMPLE, "options": MCP_OPTIONS, "chosen": ()}
    fields.update(overrides)
    return McpSelectionScreen(**fields)


class McpSelectionScreenTest(unittest.TestCase):
    """A checklist rather than a menu of one-way choices: `CHOOSE` toggles a
    server in or out of `chosen` without ever leaving the screen, and only
    reaching the row after the last one and choosing that is real engine
    work, left inert here the same way every other `_ENGINE_TARGETS` member
    already is."""

    def test_choosing_an_unchecked_server_checks_it_and_keeps_the_cursor(self):
        navigator = Navigator.starting().opened(_mcp_screen())
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator.current.chosen, ("cbm",))
        self.assertEqual(navigator.cursor, 0)

    def test_choosing_a_checked_server_again_unchecks_it(self):
        navigator = Navigator.starting().opened(_mcp_screen(chosen=("cbm",)))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator.current.chosen, ())

    def test_toggling_one_server_never_touches_another(self):
        navigator = Navigator.starting().opened(_mcp_screen(chosen=("context7",))).handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator.current.chosen, ())
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator.current.chosen, ("context7",))

    def test_moving_down_past_the_last_server_reaches_continue(self):
        navigator = Navigator.starting().opened(_mcp_screen())
        for _ in range(len(MCP_OPTIONS)):
            navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.cursor, len(MCP_OPTIONS))

    def test_moving_down_from_continue_wraps_to_the_first_server(self):
        navigator = Navigator.starting().opened(_mcp_screen())
        for _ in range(len(MCP_OPTIONS) + 1):
            navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.cursor, 0)

    def test_choosing_continue_directly_does_nothing_by_itself(self):
        """Fetching the plan for what ended up checked is real engine work
        only `session` can do; asking `Navigator` alone for it must never
        invent a screen to stand in for the report it cannot fetch."""
        navigator = Navigator.starting().opened(_mcp_screen())
        for _ in range(len(MCP_OPTIONS)):
            navigator = navigator.handle(Action.MOVE_DOWN)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)

    def test_going_back_leaves_the_selection_screen(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE)
        navigator = navigator.opened(_mcp_screen())
        navigator = navigator.handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)

    def test_toggle_checks_an_unchecked_server_the_same_way_choose_does(self):
        navigator = Navigator.starting().opened(_mcp_screen())
        navigator = navigator.handle(Action.TOGGLE)
        self.assertEqual(navigator.current.chosen, ("cbm",))
        self.assertEqual(navigator.cursor, 0)

    def test_toggle_unchecks_a_checked_server(self):
        navigator = Navigator.starting().opened(_mcp_screen(chosen=("cbm",)))
        navigator = navigator.handle(Action.TOGGLE)
        self.assertEqual(navigator.current.chosen, ())

    def test_toggle_on_continue_does_nothing_by_itself(self):
        """Space means "toggle this", and Continue is not a togglable thing."""
        navigator = Navigator.starting().opened(_mcp_screen())
        for _ in range(len(MCP_OPTIONS)):
            navigator = navigator.handle(Action.MOVE_DOWN)
        before = navigator
        navigator = navigator.handle(Action.TOGGLE)
        self.assertEqual(navigator, before)


class StatusEntryTest(unittest.TestCase):
    """`Status and diagnostics` always leads somewhere real — `doctor` never
    needs a CLI detected first the way `install` does — but building its
    report is real engine work, so `Navigator` alone treats choosing it the
    same inert way it treats an `InstallTarget`."""

    def test_the_main_menu_names_a_status_request(self):
        target = next(entry.target for entry in main_menu().entries if entry.label == "Status and diagnostics")
        self.assertIsInstance(target, StatusRequest)

    def test_choosing_it_directly_does_nothing_by_itself(self):
        navigator = Navigator.starting()
        status_index = [entry.label for entry in navigator.current.entries].index("Status and diagnostics")
        for _ in range(status_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class UninstallMenuTest(unittest.TestCase):
    def test_nothing_installed_shows_a_placeholder_that_says_why(self):
        navigator = Navigator.starting(installed=())
        uninstall_index = [entry.label for entry in navigator.current.entries].index("Uninstall")
        for _ in range(uninstall_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Placeholder)

    def test_an_installed_cli_opens_a_menu_naming_it(self):
        menu = uninstall_menu(installed=(SAMPLE,))
        self.assertIsInstance(menu, Menu)
        self.assertEqual(menu.entries[0].target, UninstallTarget(SAMPLE))

    def test_choosing_an_installed_cli_directly_does_nothing_by_itself(self):
        navigator = Navigator.starting(installed=(SAMPLE,))
        uninstall_index = [entry.label for entry in navigator.current.entries].index("Uninstall")
        for _ in range(uninstall_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class RestoreMenuTest(unittest.TestCase):
    def test_no_generation_shows_a_placeholder_that_says_why(self):
        self.assertIsInstance(restore_menu(generations=()), Placeholder)

    def test_a_generation_opens_a_menu_naming_it(self):
        menu = restore_menu(generations=(3, 2, 1))
        self.assertIsInstance(menu, Menu)
        self.assertEqual([entry.target for entry in menu.entries], [RestoreTarget(3), RestoreTarget(2), RestoreTarget(1)])

    def test_choosing_a_generation_directly_does_nothing_by_itself(self):
        navigator = Navigator.starting().opened(restore_menu(generations=(1,)))
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class ConfirmTargetsTest(unittest.TestCase):
    """`UninstallConfirm` and `RestoreConfirm` name real engine work too,
    just like their outer counterparts — choosing either directly is inert
    until `session` acts on it."""

    def confirm_menu(self, target) -> Menu:
        return Menu(title="Confirm?", entries=(Entry("Cancel", CANCEL), Entry("Confirm", target)))

    def test_choosing_a_confirm_target_directly_does_nothing_by_itself(self):
        for target in (UninstallConfirm(SAMPLE), RestoreConfirm(1)):
            navigator = Navigator.starting().opened(self.confirm_menu(target)).handle(Action.MOVE_DOWN)
            before = navigator
            navigator = navigator.handle(Action.CHOOSE)
            self.assertEqual(navigator, before)

    def test_choosing_cancel_leaves_the_screen_without_touching_anything(self):
        navigator = Navigator.starting().opened(self.confirm_menu(UninstallConfirm(SAMPLE)))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current, Navigator.starting().current)

    def test_the_default_cursor_on_a_confirm_menu_sits_on_cancel(self):
        navigator = Navigator.starting().opened(self.confirm_menu(UninstallConfirm(SAMPLE)))
        self.assertEqual(navigator.cursor, 0)
        self.assertEqual(navigator.current.entries[navigator.cursor].label, "Cancel")


class ResultScreensReturnToTheMainMenuTest(unittest.TestCase):
    def test_acknowledging_an_uninstall_result_leaves_it(self):
        navigator = Navigator.starting().opened(UninstallResultScreen(cli=SAMPLE, report={"status": "uninstalled"}))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)

    def test_acknowledging_a_restore_result_leaves_it(self):
        navigator = Navigator.starting().opened(RestoreResultScreen(report={"status": "restored"}))
        navigator = navigator.handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)


class MenuPrefaceTest(unittest.TestCase):
    def test_a_menu_with_no_preface_behaves_exactly_as_before(self):
        menu = Menu(title="t", entries=(Entry("a", CANCEL),))
        self.assertEqual(menu.preface, ())


class ModelsMenuTest(unittest.TestCase):
    def test_a_detected_cli_opens_a_menu_naming_it(self):
        menu = models_menu(detections=(SAMPLE,))
        self.assertIsInstance(menu, Menu)
        self.assertIsInstance(menu.entries[0].target, ModelsTarget)
        self.assertEqual(menu.entries[0].target.cli, SAMPLE)

    def test_no_detected_cli_still_shows_a_placeholder_that_says_why(self):
        menu = models_menu(detections=())
        self.assertIsInstance(menu, Placeholder)

    def test_choosing_a_cli_directly_does_nothing_by_itself(self):
        navigator = Navigator(_stack=(models_menu(detections=(SAMPLE,)),), _cursors=(0,))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)


class ModelsWizardRowsStepTest(unittest.TestCase):
    def test_moving_the_cursor_wraps_across_rows(self):
        navigator = Navigator(_stack=(_models_screen(),), _cursors=(1,))
        navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.cursor, 0)

    def test_choosing_a_row_fills_in_the_agent(self):
        navigator = Navigator(_stack=(_models_screen(),), _cursors=(0,))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator.current.agent, "sdd-apply")
        self.assertEqual(navigator.cursor, 0)

    def test_removing_an_assignment_does_nothing_by_itself(self):
        navigator = Navigator(_stack=(_models_screen(),), _cursors=(0,))
        navigator = navigator.handle(Action.REMOVE)
        self.assertIsNone(navigator.current.agent)

    def test_back_at_the_rows_step_leaves_the_wizard(self):
        navigator = Navigator.starting().opened(_models_screen())
        navigator = navigator.handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)


class ModelsWizardProviderStepTest(unittest.TestCase):
    def test_choosing_an_agent_then_a_provider_fills_in_both(self):
        navigator = Navigator(_stack=(_models_screen(agent="sdd-apply"),), _cursors=(1,))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator.current.provider_id, "openai")
        self.assertEqual(navigator.cursor, 0)

    def test_back_clears_the_agent_rather_than_leaving_the_wizard(self):
        navigator = Navigator(_stack=(_models_screen(agent="sdd-apply"),), _cursors=(0,))
        navigator = navigator.handle(Action.BACK)
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertIsNone(navigator.current.agent)


class ModelsWizardModelStepTest(unittest.TestCase):
    def test_choosing_a_reasoning_model_moves_to_the_effort_step(self):
        navigator = Navigator(_stack=(_models_screen(agent="sdd-apply", provider_id="anthropic"),), _cursors=(0,))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator.current.model_id, "deep-thinker")

    def test_choosing_a_plain_model_is_a_commit_left_to_session(self):
        navigator = Navigator(_stack=(_models_screen(agent="sdd-apply", provider_id="openai"),), _cursors=(0,))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsNone(navigator.current.model_id)

    def test_back_clears_the_provider_rather_than_leaving_the_wizard(self):
        navigator = Navigator(_stack=(_models_screen(agent="sdd-apply", provider_id="anthropic"),), _cursors=(0,))
        navigator = navigator.handle(Action.BACK)
        self.assertIsNone(navigator.current.provider_id)
        self.assertEqual(navigator.current.agent, "sdd-apply")


class ModelsWizardEffortStepTest(unittest.TestCase):
    def test_choosing_an_effort_is_a_commit_left_to_session(self):
        screen = _models_screen(agent="sdd-apply", provider_id="anthropic", model_id="deep-thinker")
        navigator = Navigator(_stack=(screen,), _cursors=(0,))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIs(navigator.current, screen)

    def test_back_clears_the_model_rather_than_leaving_the_wizard(self):
        screen = _models_screen(agent="sdd-apply", provider_id="anthropic", model_id="deep-thinker")
        navigator = Navigator(_stack=(screen,), _cursors=(0,))
        navigator = navigator.handle(Action.BACK)
        self.assertIsNone(navigator.current.model_id)
        self.assertEqual(navigator.current.provider_id, "anthropic")


class BusyMessageOnMenuTest(unittest.TestCase):
    """What `busy_message_for` says before a menu choice that `Navigator`
    itself leaves a no-op for `session.step` to catch."""

    def setUp(self):
        self.menu = main_menu(detections=(SAMPLE,), installed=(SAMPLE,))

    def test_ordinary_movement_says_nothing(self):
        self.assertIsNone(busy_message_for(self.menu, 0, Action.MOVE_DOWN))
        self.assertIsNone(busy_message_for(self.menu, 0, Action.MOVE_UP))
        self.assertIsNone(busy_message_for(self.menu, 0, Action.BACK))

    def test_opening_a_submenu_from_the_main_menu_says_nothing(self):
        # Choosing "Install", "Configure models", or "Uninstall" on the main
        # menu only opens the submenu listing detected CLIs -- pure
        # navigation, one level above the entry that names real work.
        labels = [entry.label for entry in self.menu.entries]
        for label in ("Install", "Configure models", "Uninstall"):
            self.assertIsNone(busy_message_for(self.menu, labels.index(label), Action.CHOOSE))

    def test_choosing_status_says_what_it_will_do(self):
        index = [entry.label for entry in self.menu.entries].index("Status and diagnostics")
        message = busy_message_for(self.menu, index, Action.CHOOSE)
        self.assertEqual(message, "Running diagnostics…")

    def test_choosing_a_cli_on_the_install_submenu_names_it(self):
        message = busy_message_for(install_menu((SAMPLE,)), 0, Action.CHOOSE)
        self.assertIn(SAMPLE.display_name, message)

    def test_choosing_a_cli_on_the_models_submenu_names_it(self):
        message = busy_message_for(models_menu((SAMPLE,)), 0, Action.CHOOSE)
        self.assertIn(SAMPLE.display_name, message)

    def test_choosing_a_cli_on_the_uninstall_submenu_names_it(self):
        message = busy_message_for(uninstall_menu((SAMPLE,)), 0, Action.CHOOSE)
        self.assertIn(SAMPLE.display_name, message)

    def test_choosing_exit_says_nothing_because_quitting_is_not_engine_work(self):
        exit_index = [entry.label for entry in self.menu.entries].index("Exit")
        self.assertIsNone(busy_message_for(self.menu, exit_index, Action.CHOOSE))

    def test_choosing_cancel_says_nothing(self):
        menu = Menu(title="x", entries=(Entry("Cancel", CANCEL),))
        self.assertIsNone(busy_message_for(menu, 0, Action.CHOOSE))

    def test_uninstall_confirm_and_restore_confirm_name_what_they_touch(self):
        confirm_menu = Menu(
            title="x",
            entries=(Entry("a", UninstallConfirm(SAMPLE)), Entry("b", RestoreConfirm(7))),
        )
        uninstall_message = busy_message_for(confirm_menu, 0, Action.CHOOSE)
        restore_message = busy_message_for(confirm_menu, 1, Action.CHOOSE)
        self.assertIn(SAMPLE.display_name, uninstall_message)
        self.assertIn("7", restore_message)

    def test_restore_target_names_the_generation(self):
        menu = restore_menu((3, 1))
        message = busy_message_for(menu, 0, Action.CHOOSE)
        self.assertIn("3", message)


class BusyMessageOnMcpSelectionTest(unittest.TestCase):
    def setUp(self):
        self.screen = McpSelectionScreen(
            cli=SAMPLE,
            options=(McpOption(id="one", description="d"), McpOption(id="two", description="d")),
            chosen=(),
        )

    def test_toggling_a_server_says_nothing(self):
        self.assertIsNone(busy_message_for(self.screen, 0, Action.CHOOSE))
        self.assertIsNone(busy_message_for(self.screen, 1, Action.CHOOSE))

    def test_continue_names_the_cli(self):
        continue_row = len(self.screen.options)
        message = busy_message_for(self.screen, continue_row, Action.CHOOSE)
        self.assertIn(SAMPLE.display_name, message)

    def test_movement_says_nothing(self):
        self.assertIsNone(busy_message_for(self.screen, 0, Action.MOVE_DOWN))

    def test_toggle_says_nothing(self):
        self.assertIsNone(busy_message_for(self.screen, 0, Action.TOGGLE))
        continue_row = len(self.screen.options)
        self.assertIsNone(busy_message_for(self.screen, continue_row, Action.TOGGLE))


class BusyMessageOnInstallPlanTest(unittest.TestCase):
    def test_choosing_names_the_cli(self):
        screen = InstallPlanScreen(cli=SAMPLE, report={})
        message = busy_message_for(screen, 0, Action.CHOOSE)
        self.assertIn(SAMPLE.display_name, message)

    def test_back_says_nothing(self):
        screen = InstallPlanScreen(cli=SAMPLE, report={})
        self.assertIsNone(busy_message_for(screen, 0, Action.BACK))


class BusyMessageOnStatusScreenTest(unittest.TestCase):
    def test_choosing_says_something(self):
        screen = StatusScreen(report={})
        message = busy_message_for(screen, 0, Action.CHOOSE)
        self.assertIsNotNone(message)
        self.assertNotEqual(message, "")

    def test_back_says_nothing(self):
        screen = StatusScreen(report={})
        self.assertIsNone(busy_message_for(screen, 0, Action.BACK))


class BusyMessageOnModelsWizardTest(unittest.TestCase):
    def test_the_rows_step_says_nothing_for_a_pure_choose(self):
        screen = _models_screen()
        self.assertIsNone(busy_message_for(screen, 0, Action.CHOOSE))

    def test_removing_an_assignment_names_the_agent(self):
        screen = _models_screen()
        message = busy_message_for(screen, 0, Action.REMOVE)
        self.assertIn(ROWS[0].agent, message)

    def test_removing_with_no_rows_says_nothing(self):
        screen = _models_screen(rows=())
        self.assertIsNone(busy_message_for(screen, 0, Action.REMOVE))

    def test_the_provider_step_says_nothing_for_a_pure_choose(self):
        screen = _models_screen(agent="sdd-apply")
        self.assertIsNone(busy_message_for(screen, 0, Action.CHOOSE))

    def test_choosing_a_reasoning_model_says_nothing_because_the_wizard_only_narrows(self):
        screen = _models_screen(agent="sdd-apply", provider_id="anthropic")
        self.assertIsNone(busy_message_for(screen, 0, Action.CHOOSE))

    def test_choosing_a_plain_model_names_the_agent(self):
        screen = _models_screen(agent="sdd-apply", provider_id="openai")
        message = busy_message_for(screen, 0, Action.CHOOSE)
        self.assertIn("sdd-apply", message)

    def test_choosing_an_effort_names_the_agent(self):
        screen = _models_screen(agent="sdd-apply", provider_id="anthropic", model_id="deep-thinker")
        message = busy_message_for(screen, 0, Action.CHOOSE)
        self.assertIn("sdd-apply", message)

    def test_movement_and_back_say_nothing_anywhere_in_the_wizard(self):
        for screen in (
            _models_screen(),
            _models_screen(agent="sdd-apply"),
            _models_screen(agent="sdd-apply", provider_id="anthropic"),
            _models_screen(agent="sdd-apply", provider_id="anthropic", model_id="deep-thinker"),
        ):
            self.assertIsNone(busy_message_for(screen, 0, Action.MOVE_DOWN))
            self.assertIsNone(busy_message_for(screen, 0, Action.BACK))


class StartupMessageTest(unittest.TestCase):
    def test_it_is_a_real_sentence(self):
        self.assertIsInstance(STARTUP_MESSAGE, str)
        self.assertTrue(STARTUP_MESSAGE.strip())


if __name__ == "__main__":
    unittest.main()


class EveryEngineTargetSaysWhatItIsDoingTest(unittest.TestCase):
    """The sentence and the work are written in two places, and they can drift.

    `session.step` decides what runs; `busy_message_for` decides what is said
    before it runs. Neither module reads the other, so adding a target to one
    and forgetting the other leaves the screen either claiming to be idle
    while it works — the defect this was written to fix, back again — or
    naming work that never happens.

    This closes the half of that gap that is a declared set: every target
    `Navigator` leaves for `session` to act on must have something to say.
    The other half lives in conditions inside `session.step` for three
    screens, and no set enumerates those, so a change to its branching is
    still a reason to come and read this module.
    """

    def target_for(self, kind):
        made = {
            InstallTarget: lambda: InstallTarget(CliOption("probe", "Probe", "/probe", "full")),
            StatusRequest: lambda: StatusRequest(),
            UninstallTarget: lambda: UninstallTarget(CliOption("probe", "Probe", "/probe", "full")),
            UninstallConfirm: lambda: UninstallConfirm(CliOption("probe", "Probe", "/probe", "full")),
            RestoreTarget: lambda: RestoreTarget(1),
            RestoreConfirm: lambda: RestoreConfirm(1),
            ModelsTarget: lambda: ModelsTarget(CliOption("probe", "Probe", "/probe", "full")),
            UpdateTarget: lambda: UpdateTarget(CliOption("probe", "Probe", "/probe", "full")),
            UpgradeTarget: lambda: UpgradeTarget(),
        }
        return made[kind]()

    def test_every_declared_engine_target_has_something_to_say(self):
        for kind in navigator_module._ENGINE_TARGETS:
            with self.subTest(target=kind.__name__):
                menu = Menu(title="probe", entries=(Entry("only", self.target_for(kind)),))
                message = navigator_module.busy_message_for(menu, 0, Action.CHOOSE)
                self.assertIsNotNone(message, f"{kind.__name__} runs an engine call and says nothing")
                self.assertTrue(message.strip(), f"{kind.__name__} says only whitespace")


class UpdateMenuTest(unittest.TestCase):
    """`update_menu`: only a CLI Pegasus is actually installed into can be
    offered -- `update` refuses otherwise, and offering an action that can
    only fail is worse than not offering it at all."""

    def test_nothing_installed_is_a_placeholder_naming_the_reason(self):
        menu = update_menu(installed=())
        self.assertIsInstance(menu, Placeholder)
        self.assertTrue(menu.note)

    def test_an_installed_cli_opens_a_menu_naming_it(self):
        menu = update_menu(installed=(SAMPLE,))
        self.assertIsInstance(menu, Menu)
        self.assertEqual(menu.entries[0].target, UpdateTarget(SAMPLE))

    def test_the_main_menu_offers_update_only_for_what_is_installed(self):
        without = main_menu(detections=(SAMPLE,), installed=())
        target = next(entry.target for entry in without.entries if entry.label == "Update")
        self.assertIsInstance(target, Placeholder)

        withit = main_menu(detections=(SAMPLE,), installed=(SAMPLE,))
        target = next(entry.target for entry in withit.entries if entry.label == "Update")
        self.assertIsInstance(target, Menu)
        self.assertEqual(target.entries[0].target, UpdateTarget(SAMPLE))

    def test_opening_the_update_submenu_from_the_main_menu_says_nothing(self):
        """Landing on the `Update` entry itself only opens the submenu
        listing installed CLIs -- pure navigation, one level above the
        entry that actually names real work."""
        menu = main_menu(detections=(SAMPLE,), installed=(SAMPLE,))
        update_index = [entry.label for entry in menu.entries].index("Update")
        self.assertIsNone(busy_message_for(menu, update_index, Action.CHOOSE))

    def test_choosing_a_cli_on_the_update_submenu_directly_does_nothing_by_itself(self):
        """Fetching the update plan is real engine work, left to `session` --
        the same reasoning every other `_ENGINE_TARGETS` member follows."""
        navigator = Navigator.starting(installed=(SAMPLE,))
        update_index = [entry.label for entry in navigator.current.entries].index("Update")
        for _ in range(update_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)  # opens the update submenu
        self.assertIsInstance(navigator.current, Menu)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)  # chooses the one installed CLI
        self.assertEqual(navigator, before)

    def test_choosing_a_cli_on_the_update_submenu_says_what_it_will_do(self):
        message = busy_message_for(update_menu((SAMPLE,)), 0, Action.CHOOSE)
        self.assertIsNotNone(message)
        self.assertIn(SAMPLE.display_name, message)


class UpdatePlanAndResultWordingTest(unittest.TestCase):
    """`InstallPlanScreen`/`InstallResultScreen` are shared between the
    Install and Update flows -- `command` is what tells the busy message,
    and later the renderer, which one this run of the confirmation is."""

    def test_the_default_command_is_install(self):
        screen = InstallPlanScreen(cli=SAMPLE, report={})
        self.assertEqual(screen.command, "install")

    def test_confirming_an_install_plan_says_installing(self):
        screen = InstallPlanScreen(cli=SAMPLE, report={}, command="install")
        message = busy_message_for(screen, 0, Action.CHOOSE)
        self.assertIn("Installing", message)
        self.assertIn(SAMPLE.display_name, message)

    def test_confirming_an_update_plan_says_updating_not_installing(self):
        screen = InstallPlanScreen(cli=SAMPLE, report={}, command="update")
        message = busy_message_for(screen, 0, Action.CHOOSE)
        self.assertIn("Updating", message)
        self.assertNotIn("Installing", message)
        self.assertIn(SAMPLE.display_name, message)


class UpgradeMenuEntryTest(unittest.TestCase):
    """`Upgrade`: unlike `Update`, needs no CLI and no submenu -- one entry on
    the main menu, naming `pegasus upgrade` directly."""

    def test_the_main_menu_names_an_upgrade_target(self):
        target = next(entry.target for entry in main_menu().entries if entry.label == "Upgrade")
        self.assertEqual(target, UpgradeTarget())
        self.assertEqual(target.command, "upgrade")

    def test_choosing_upgrade_on_the_main_menu_does_nothing_by_itself(self):
        """Real engine work -- checking the newest published release -- is
        `session`'s job, the same reasoning every other `_ENGINE_TARGETS`
        member follows."""
        navigator = Navigator.starting()
        upgrade_index = [entry.label for entry in navigator.current.entries].index("Upgrade")
        for _ in range(upgrade_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)

    def test_choosing_upgrade_says_what_it_will_do(self):
        menu = main_menu()
        upgrade_index = [entry.label for entry in menu.entries].index("Upgrade")
        message = busy_message_for(menu, upgrade_index, Action.CHOOSE)
        self.assertIsNotNone(message)

    def test_confirming_an_upgrade_plan_says_something_other_than_installing_or_updating(self):
        screen = InstallPlanScreen(cli=PEGASUS_PROGRAM, report={}, command="upgrade")
        message = busy_message_for(screen, 0, Action.CHOOSE)
        self.assertIsNotNone(message)
        self.assertNotIn("Installing", message)
        self.assertNotIn("Updating", message)


class RemoteUpdateRemedyTest(unittest.TestCase):
    """The remote notice used to point at a manual download; it now points at
    the `Upgrade` action that can actually do it."""

    def test_the_remedy_now_names_upgrade_rather_than_a_manual_download(self):
        self.assertIn("Upgrade", REMOTE_UPDATE_REMEDY)
        self.assertNotIn("download", REMOTE_UPDATE_REMEDY.lower())

    def test_the_remote_notice_line_uses_the_updated_remedy(self):
        notice = UpdateNotice(running="5.10.0", remote_latest="5.11.0")
        lines = update_notice_lines(notice)
        self.assertTrue(any(REMOTE_UPDATE_REMEDY in line for line in lines))


class UpdateNoticeTest(unittest.TestCase):
    """The two-fact notice on the main menu, decided from plain version
    strings so it never needs a clock, a socket, or the filesystem to test.

    The local half is now a list of :class:`BehindInstall`, one per
    installed CLI, each naming itself -- unlike the old single
    `local_recorded` string, which spoke for an arbitrary CLI whenever more
    than one was installed at different recorded versions."""

    def test_no_facts_at_all_says_nothing(self):
        notice = UpdateNotice(running="5.10.0")
        self.assertEqual(update_notice_lines(notice), ())

    def test_a_local_install_behind_the_running_binary_names_it_and_update_as_the_remedy(self):
        notice = UpdateNotice(
            running="5.10.0", local_behind=(BehindInstall(display_name="Demo CLI", recorded="5.9.0"),)
        )
        lines = update_notice_lines(notice)
        self.assertTrue(lines)
        self.assertTrue(any("Update" in line for line in lines))
        self.assertTrue(any("Demo CLI" in line for line in lines))
        self.assertTrue(any("5.9.0" in line for line in lines))
        self.assertTrue(any("5.10.0" in line for line in lines))

    def test_a_local_install_whose_update_would_refuse_names_the_remedy_command_not_update(self):
        """The primary fix for the defect this test pins: the notice must
        never recommend `Update` for an installation `update` will refuse
        outright over an unresolved bound mcp server key."""
        notice = UpdateNotice(
            running="5.10.0",
            local_behind=(
                BehindInstall(
                    display_name="Demo CLI",
                    recorded="5.9.0",
                    remedy_command="pegasus install --cli demo --mcp cbm=<key>",
                ),
            ),
        )
        lines = update_notice_lines(notice)
        self.assertEqual(len(lines), 1)
        self.assertNotIn("choose Update", lines[0])
        self.assertIn("Demo CLI", lines[0])
        self.assertIn("pegasus install --cli demo --mcp cbm=<key>", lines[0])

    def test_two_behind_installs_are_both_named_on_their_own_lines(self):
        notice = UpdateNotice(
            running="5.10.0",
            local_behind=(
                BehindInstall(display_name="Demo CLI", recorded="5.9.0"),
                BehindInstall(display_name="Other CLI", recorded="5.8.0"),
            ),
        )
        lines = update_notice_lines(notice)
        self.assertEqual(len(lines), 2)
        self.assertTrue(any("Demo CLI" in line and "5.9.0" in line for line in lines))
        self.assertTrue(any("Other CLI" in line and "5.8.0" in line for line in lines))

    def test_a_local_install_matching_the_running_binary_says_nothing(self):
        notice = UpdateNotice(
            running="5.10.0", local_behind=(BehindInstall(display_name="Demo CLI", recorded="5.10.0"),)
        )
        self.assertEqual(update_notice_lines(notice), ())

    def test_a_local_install_newer_than_the_running_binary_says_nothing(self):
        """Should never happen in practice, but guessing an ordering that
        implies the binary itself regressed is worse than saying nothing."""
        notice = UpdateNotice(
            running="5.10.0", local_behind=(BehindInstall(display_name="Demo CLI", recorded="5.11.0"),)
        )
        self.assertEqual(update_notice_lines(notice), ())

    def test_a_missing_recorded_version_says_nothing_about_it(self):
        notice = UpdateNotice(
            running="5.10.0", local_behind=(BehindInstall(display_name="Demo CLI", recorded=None),)
        )
        self.assertEqual(update_notice_lines(notice), ())

    def test_a_newer_remote_release_does_not_name_update_as_the_remedy(self):
        """`update` is local-only and can never fetch the new binary -- the
        remote notice must never suggest it can."""
        notice = UpdateNotice(running="5.10.0", remote_latest="5.11.0")
        lines = update_notice_lines(notice)
        self.assertTrue(lines)
        self.assertFalse(any("Update" in line for line in lines), lines)
        self.assertTrue(any("5.11.0" in line for line in lines))

    def test_a_remote_release_no_newer_than_the_running_binary_says_nothing(self):
        notice = UpdateNotice(running="5.10.0", remote_latest="5.10.0")
        self.assertEqual(update_notice_lines(notice), ())

    def test_both_facts_can_appear_together_and_stay_distinct(self):
        notice = UpdateNotice(
            running="5.10.0",
            local_behind=(BehindInstall(display_name="Demo CLI", recorded="5.9.0"),),
            remote_latest="5.11.0",
        )
        lines = update_notice_lines(notice)
        self.assertEqual(len(lines), 2)
        local_line = next(line for line in lines if "5.9.0" in line)
        remote_line = next(line for line in lines if "5.11.0" in line)
        self.assertIn("Update", local_line)
        self.assertNotIn("Update", remote_line)

    def test_an_unparseable_local_version_says_nothing_about_it(self):
        notice = UpdateNotice(
            running="5.10.0", local_behind=(BehindInstall(display_name="Demo CLI", recorded="not-a-version"),)
        )
        self.assertEqual(update_notice_lines(notice), ())

    def test_an_unparseable_remote_version_says_nothing_about_it(self):
        notice = UpdateNotice(running="5.10.0", remote_latest="not-a-version")
        self.assertEqual(update_notice_lines(notice), ())

    def test_an_unparseable_running_version_says_nothing_at_all(self):
        notice = UpdateNotice(
            running="not-a-version",
            local_behind=(BehindInstall(display_name="Demo CLI", recorded="5.9.0"),),
            remote_latest="5.11.0",
        )
        self.assertEqual(update_notice_lines(notice), ())


class MainMenuCarriesTheNoticeTest(unittest.TestCase):
    def test_starting_with_a_notice_shows_it_as_the_menus_preface(self):
        notice = UpdateNotice(
            running="5.10.0", local_behind=(BehindInstall(display_name="Demo CLI", recorded="5.9.0"),)
        )
        navigator = Navigator.starting(notice=notice)
        self.assertEqual(navigator.current.preface, update_notice_lines(notice))

    def test_no_notice_given_is_the_same_as_an_empty_one(self):
        navigator = Navigator.starting()
        self.assertEqual(navigator.current.preface, ())


class NavigatorWithNoticeTest(unittest.TestCase):
    """`Navigator.with_notice`: how the remote half of the notice reaches the
    main menu once a background check resolves, well after the first frame
    -- and, possibly, well after a person has already navigated on."""

    def test_applies_to_the_main_menu_at_the_bottom_of_the_stack(self):
        navigator = Navigator.starting()
        notice = UpdateNotice(running="5.10.0", remote_latest="5.11.0")
        navigator = navigator.with_notice(notice)
        self.assertEqual(navigator.current.preface, update_notice_lines(notice))

    def test_applies_even_after_navigating_away_from_the_main_menu(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)  # the install submenu, not the main menu
        notice = UpdateNotice(running="5.10.0", remote_latest="5.11.0")
        navigator = navigator.with_notice(notice)
        self.assertNotEqual(navigator.current.preface, update_notice_lines(notice))
        navigator = navigator.handle(Action.BACK)
        self.assertEqual(navigator.current.preface, update_notice_lines(notice))

    def test_does_not_disturb_the_cursor_anywhere_on_the_stack(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.MOVE_DOWN)
        cursor_before = navigator.cursor
        navigator = navigator.with_notice(UpdateNotice(running="5.10.0"))
        self.assertEqual(navigator.cursor, cursor_before)
