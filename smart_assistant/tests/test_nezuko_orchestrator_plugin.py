from types import SimpleNamespace

import nezuko_orchestrator_plugin as nop


class Command:
    def __init__(self, name, description="documented"):
        self.name, self.description = name, description


class Registry:
    def __init__(self, names):
        self.commands = {name: Command(name) for name in names}

    def list_commands(self):
        return list(self.commands.values())

    def get(self, name):
        return self.commands.get(name)


def _engine(names):
    return SimpleNamespace(
        registry=Registry(names),
        plugin_health={"media": {"status": "loaded", "commands": list(names), "collisions": []}},
    )


def test_integrated_audit_counts_commands_and_workflows():
    names = {step for flow in nop.WORKFLOWS.values() for step in flow.steps}
    engine = _engine(names)
    result = nop._cmd_nezuko_integrate(SimpleNamespace(args=[], engine=engine))
    assert f"Commands: {len(names)} integrated" in result
    assert f"Workflows: {len(nop.WORKFLOWS)}/{len(nop.WORKFLOWS)} complete" in result
    assert "Broken plugins" not in result


def test_workflow_reports_missing_stage():
    engine = _engine({"channel_view_growth_lab"})
    result = nop._cmd_nezuko_workflow(SimpleNamespace(args=["growth_video"], engine=engine))
    assert "✅ channel_view_growth_lab" in result
    assert "❌ youtube_video_analyze" in result


def test_unknown_workflow_is_clear():
    result = nop._cmd_nezuko_workflow(SimpleNamespace(args=["unknown"], engine=_engine(set())))
    assert result.startswith("❌")
    assert "growth_video" in result


def test_registers_orchestrator_commands():
    names = []

    class R:
        def register(self, name, handler, description=""):
            names.append(name)

    nop.register(SimpleNamespace(registry=R()))
    assert names == ["jarvis_integrate", "jarvis_workflow", "jarvis_evolve",
                     "nezuko_integrate", "nezuko_workflow", "nezuko_evolve"]
