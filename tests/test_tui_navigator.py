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
    UninstallConfirm,
    UninstallResultScreen,
    UninstallTarget,
    busy_message_for,
    install_menu,
    main_menu,
    models_menu,
    restore_menu,
    uninstall_menu,
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

    def test_the_main_menu_has_the_five_documented_entries_in_order(self):
        navigator = Navigator.starting()
        labels = [entry.label for entry in navigator.current.entries]
        self.assertEqual(
            labels,
            ["Install", "Configure models", "Status and diagnostics", "Uninstall", "Exit"],
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


class StatusEntryTest(unittest.TestCase):
    """`Status and diagnostics` always leads somewhere real — `doctor` never
    needs a CLI detected first the way `install` does — but building its
    report is real engine work, so `Navigator` alone treats choosing it the
    same inert way it treats an `InstallTarget`."""

    def test_the_main_menu_names_a_status_request(self):
        self.assertIsInstance(main_menu().entries[2].target, StatusRequest)

    def test_choosing_it_directly_does_nothing_by_itself(self):
        navigator = Navigator.starting()
        for _ in range(2):
            navigator = navigator.handle(Action.MOVE_DOWN)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class UninstallMenuTest(unittest.TestCase):
    def test_nothing_installed_shows_a_placeholder_that_says_why(self):
        navigator = Navigator.starting(installed=()).handle(Action.MOVE_DOWN).handle(Action.MOVE_DOWN).handle(
            Action.MOVE_DOWN
        )
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Placeholder)

    def test_an_installed_cli_opens_a_menu_naming_it(self):
        menu = uninstall_menu(installed=(SAMPLE,))
        self.assertIsInstance(menu, Menu)
        self.assertEqual(menu.entries[0].target, UninstallTarget(SAMPLE))

    def test_choosing_an_installed_cli_directly_does_nothing_by_itself(self):
        navigator = Navigator.starting(installed=(SAMPLE,))
        for _ in range(3):
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
        for index in (0, 1, 3):
            self.assertIsNone(busy_message_for(self.menu, index, Action.CHOOSE))

    def test_choosing_status_says_what_it_will_do(self):
        message = busy_message_for(self.menu, 2, Action.CHOOSE)
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
        self.assertIsNone(busy_message_for(self.menu, 4, Action.CHOOSE))

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
        }
        return made[kind]()

    def test_every_declared_engine_target_has_something_to_say(self):
        for kind in navigator_module._ENGINE_TARGETS:
            with self.subTest(target=kind.__name__):
                menu = Menu(title="probe", entries=(Entry("only", self.target_for(kind)),))
                message = navigator_module.busy_message_for(menu, 0, Action.CHOOSE)
                self.assertIsNotNone(message, f"{kind.__name__} runs an engine call and says nothing")
                self.assertTrue(message.strip(), f"{kind.__name__} says only whitespace")
